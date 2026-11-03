# The proxy's frame capture (`dev.capture`)

The owner of the capture's contract: config keys, the ctl verb and its result, the threads and the state machine, and the `frame.txt` record
format. Code: `proxy/src/capture.cpp` (the driver: device and state-block hooks, files, events), `proxy/src/capture.h` (pure: the shader hash, the
name and frame rules, the record formatting, the state machine), `proxy/tests/test_capture.cpp` (hash vectors, grammar, the state machine with a
two-thread stress case, source lints). Offline reader: `discovery/shader_catalog.py` `summarize()` (`discovery/tests/test_shader_catalog.py`).
Built in napoleon J8; timeout path, recording thread and state blocks in W19 (B32, B33, B34).

## Keys
| Key | What |
|---|---|
| `dev.capture` | `1` hooks 37 `IDirect3DDevice9` slots and 2 `IDirect3DStateBlock9` slots at `CreateDevice`; `0` (default, release) hooks nothing and `Present` does nothing more. With it on and no capture running, each hook is one load and a branch before the real call. |
| `dev.capture_dir` | the folder captures are written to, outside the game folder (an uninstall stays byte-exact); empty refuses every capture |

The install log line names both counts: `capture: 37 of 37 device slots, 2 of 2 state-block slots hooked`. The state-block vtable comes from one
throwaway `D3DSBT_ALL` block made through the original `CreateStateBlock` at install (never recorded) and released at once; if that fails, the log
warns, the device hooks stay, and every result says `"state_block_hooks": false`. The device vtable survives `Reset`; a new device of the same class
shares it (the first original is kept).

## The ctl verb
`capture <name> [frames]`: a name is 1-48 of `A-Za-z0-9._-`, not starting with `.`, never reused (a folder of that name refuses); frames 1 to 8.
Writes `<dev.capture_dir>\<name>\frame.txt` and each shader's bytecode once per hash to `<dev.capture_dir>\shaders\<hash>.vs|ps` (canonical
FNV-1a-64 to the walked end token, C16).

Result members, status `ok` (or `failed` with the error when frame.txt could not be written):
`dir`, `file`, `shader_dir`, `frames`, `bytes`, `lines`, `draws`, `shaders`, `shaders_new`, `shaders_unwalked` and `shaders_size_differs` (both 0: the
walked length agrees with `GetFunction`), `record_s`, `wait_s`, `other_thread_calls`, `state_blocks_created`, `state_blocks_captured`,
`state_blocks_applied`, `state_block_hooks`.

Status `failed` with `state`:
- `"nothing recorded"`: no `Present` took the arm within the ctl timeout. Members `dir`, `wait_s`, `state_block_hooks`.
- `"abandoned"`: the recording did not finish within 30 s more. Members `dir`, `file`, `wait_s`, `state_block_hooks`; none of the recording's
  counters (the render thread may still be writing them). The render thread closes `frame.txt` at its next `Present` with an `ABANDONED` line; the
  folder stays as evidence.

Refusals: `dev.capture=0`, no hooked device, `dev.capture_dir` empty, the name exists, `a capture is running`, and `the previous capture is still
closing: it ends at the next Present` (an abandoned capture not yet closed).

## Threads and the state machine
One `LONG` holds the state; every transition is a compare-and-swap (`capture.h`: `CapArmFromCtl`, `CapOnPresent`, `CapFinish`, `CapClosed`,
`CapOnTimeout`, `CapRelease`; no lock anywhere on the hook path).

| From | To | Who, when |
|---|---|---|
| Idle | Armed | ctl: arm (after the folder is made) |
| Armed | Recording | render: a `Present`, **before** the file opens; a lost CAS (the ctl withdrew) does nothing at all |
| Armed | Idle | ctl: the first wait (the ctl timeout) ran out: `nothing recorded` |
| Recording | Done | render: the last frame's `PRESENT` written and the file closed (or the open failed), then the event |
| Recording | Abandoned | ctl: the second wait (30 s) ran out: `abandoned`; a lost CAS means Done just in time, reported normally |
| Abandoned | Idle | render: the next `Present` writes `ABANDONED`, closes the file; nobody waits |
| Done | Idle | ctl: after reading the result |

Only the ctl leaves Idle and Done; only the render thread leaves Recording for Done and Abandoned for Idle. The ctl writes nothing the render
thread reads unless the state is Idle. The event only wakes the ctl; the state decides, so a late event of an earlier capture cannot end a new one.

**The recording thread.** The thread whose `Present` takes the arm is the only one recorded. Hooked calls, `D3DPERF` events and `Present`s on any
other thread while recording are forwarded, counted (`other_thread_calls`, `OTHERTHREAD` lines) and never written. A game that draws on a thread other
than its `Present` thread records nothing and says so (`draws` 0, `other_thread_calls` large).

## `frame.txt`
One call per line in call order; numbers decimal unless named, pointers and hashes hex.

| Line | What |
|---|---|
| `CAPTURE <name> launch <id> build <id> frames <n> utc <time> scene <scene>` | the header |
| `STATE` ... `ENDSTATE` | state read back with `Get*` only. At arm: what the previous frame left bound (back buffer, targets, depth surface, then the rest). After `SBAPPLY`: the same block without `BACKBUFFER`, `RT` and `DS` (a state block holds none); a reader applies it as state without breaking a pass |
| `FRAME n` ... `PRESENT` | one frame |
| `OTHERTHREAD n` | before a frame's `PRESENT` (or `ABANDONED`): calls on other threads in that frame, when not 0 |
| `ABANDONED frame n of m` | the last line of an abandoned capture |
| `BACKBUFFER ptr` | the back buffer |
| `SURF ptr w h fmt usage pool ms msq container` | a surface at first sight; container = the texture a render target belongs to |
| `TEX ptr type levels w h d fmt usage pool` | a texture at first sight |
| `DECL ptr n s.off.type.method.usage.index ...` | a vertex declaration at first sight |
| `SHADER ptr vs\|ps hash size walked` | a shader object at first sight |
| `RT i ptr`, `DS ptr` | render target, depth surface |
| `CLEAR n flags color z stencil` | |
| `STRETCH src l t r b dst l t r b filter`, `FILL`, `UPDSURF`, `UPDTEX`, `READBACK` | surface copies |
| `VS\|PS hash` | shader binds |
| `VC\|PC start count v...` (floats, exact), `VI\|PI`, `VB\|PB` | shader constants |
| `T stage ptr`, `SS sampler type value`, `RS state value`, `TSS stage type value` | textures and states (`TSS` also in every `STATE` block from W19: stages 0-7) |
| `VP x y w h minz maxz`, `SC l t r b` | viewport, scissor |
| `VD ptr`, `FVF`, `SSRC stream vb offset stride`, `FREQ stream value`, `IDX ptr`, `XFORM state m16` | input assembly, transforms |
| `DP type start count`, `DIP type base min nv start prims`, `DPUP`, `DIPUP` | draws |
| `BEGIN`, `END` | scene |
| `SBBEGIN`, `SBEND ptr` | a recorded state block |
| `SBCREATE type ptr`, `SBCAPTURE ptr` | `CreateStateBlock`, `IDirect3DStateBlock9::Capture` |
| `SBAPPLY ptr` | `IDirect3DStateBlock9::Apply`, followed by its `STATE` readback |
| `EVENT name`, `EVENTEND`, `MARKER name` | the engine's `D3DPERF` events (recording thread only) |

A reader ignores tags it does not know (`summarize()` dispatches on the first word).
