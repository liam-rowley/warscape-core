# Battle unit orders in the proxy (`dev.orders`)

Owner of: the game-agnostic battle unit control route (`proxy/src/orders.{h,cpp}`, the `wsp.*` order functions in
`proxy/src/luabridge.cpp`, `ctl.py order` in `harness/ctl.py`). Built for napoleon-remastered J28; the game's numbers, sites, command
codes and PC evidence are in that repo (`proxy/README.md` "Battle unit orders", its `engine_facts` `*.battle.order_*`).

## What it does
- **Reads** a unit's live state from engine memory (`ReadUnit` in `orders.h`, pure, host-tested on a fake memory image): centre
  x/y/z, facing (int16 binary angle, 65536 = 360 degrees, returned in degrees [0, 360)), men alive, queued orders, the destination
  front centre and frontage width, and the engine's own `is_moving` (called on the engine thread). Every read checks the unit is in
  its own army's list (`armyIndex >= 0`); a unit on a moving frame (a ship) is refused.
- **Reads the UI's own selection** (`OrdersSelection`: the loose land units of the UI's Selection object) and the army of any unit.
- **Orders one unit per command** through the engine's own command path: Selection ctor, AddUnit (the engine refuses a routing or
  dead unit: the order is refused), the ground projection the engine's script path uses, the move command ctor, the queue push, the
  command dtor, the engine free for the selection's buffers (`OrdersMove`). Other commands (halt, formation toggles) go through the
  UI's own "current selection" dispatcher with a one-unit selection of our own (`OrdersCommand`; the codes are the game's).
- Nothing is patched or detoured: every function is called, every address and offset comes from a checked engine_sites row named by
  the adapter, every pointer is checked with `VirtualQuery` before it is read or called through, and every precondition is checked
  before the first engine call (the mingw build has no SEH).

## The C++ entry points (`dev.h`)
| Entry | Thread | What |
|---|---|---|
| `OrdersUnit(unit, state, why)` | any (is_moving: the engine thread only, else -1) | one unit's state |
| `OrdersArmy(unit, units, why)` | any | the unit's army (0: the last army seen) |
| `OrdersSelection(loose, groups, why)` | any | the UI's selection |
| `OrdersMove(unit, MoveArgs, info, why)` | the engine thread only (refuses others) | one move/face order |
| `OrdersCommand(unit, cmd, arg, info, why)` | the engine thread only | one dispatcher command |
| `OrdersPost(unit, MoveArgs)` / `OrdersPostResult(id, ok, text)` | any | queue a move for the next Lua pump |
| `OrdersPump()` / `OrdersPresent()` | the pump / Present | record the threads; run posted moves |

Pure helpers in `orders.h`: `RawFromDeg`, `DegFromRaw`, `Wrap180`, `CheckMove`, `ResolveMove` (the unit's own facing and width when
none is given), `UnitOrderable`, `CheckArrival`, `AtRest`.

## Lua (`wsp`, refused with a reason when `dev.orders=0`)
`unit_state(ref)`, `unit_list([ref])`, `selection()`, `order_move(ref, x, z, [facing], [width], [run], [queue])`,
`order_command(ref, cmd, [arg])`, `peek(addr, n)` (a probe: reads only), `orders_info()`. A unit ref is a `"0x..."` string, the
engine's `Pointer<UNIT>` userdata (its first dword), or a number n = the n-th unit of the army last read. Lua numbers are float32 in
the engine's Lua: a pointer never travels as a number.

## `ctl.py order` (rule 77: no ok without a check)
`order list`; `order <unit>[,<unit>...] move <x> <z> [facing] [width] [run]` (one value or one per unit); `order <unit>[,...] <command>`
(the route's `commands`). A number names the unit's place in the army list at the start of the call, pinned to its pointer for the rest
of it (a lost unit renumbers the others). The verb pushes every order back to back, waits for rest (the engine's `is_moving` and a still
centre for `rest_reads` reads, polled for all units in one chunk call, optionally at the route's `wait_speed`, restored after), reads
each unit back and checks: the destination front centre and width (stored at the push, so alone they prove nothing), the facing, and
the live centre behind the front on the ordered axis at about the unit's own half depth; a unit ordered away that never moved fails.
Refused: a unit the proxy cannot read or the engine refuses, bad arguments. The route block (chunk, tolerance, settle, commands, run)
is the game adapter's `ctl.routes.orders`.

## The adapter (`OrdersAdapter` in `orders.h`)
Site ids and operand offsets inside their stock bytes (checked by `proxy/tests/test_orders.cpp` against the generated table), the
selection and command object sizes, the selection's four buffer offsets, and the front/width offsets that have no engine accessor
(proven by readback in the game repo). A game without the route passes `nullptr`.
