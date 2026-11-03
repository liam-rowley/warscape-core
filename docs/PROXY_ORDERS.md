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

## Ships (J60: `ships.h`, the ship half of `orders.cpp`, `ShipsAdapter`)
Ships are their own objects with their own fleet list, so they have their own decode and entry points; the queue, the `Selection`,
the command dtor and the engine free are the land route's. `OrdersMove`/`ReadUnit` keep refusing a unit on a moving frame. The ship
half installs after the land half (`OrdersShipsInstall`) and turns off alone on a site mismatch; `GameAdapter::ships = nullptr` = no ships.
- **State** (`OrdersShip`, `OrdersFleet`, `OrdersShipSelection`; any thread, reads only): every read checks the ship vtable (a stale
  or foreign pointer is refused) and the ship's place in its army's fleet list; position, heading (the engine getter's
  `atan2(m02, m22)` int16), the live sail level and the setting the engine reports, the engine's blocking flags and surrender, the
  wind when its chain is readable. No speed: the engine keeps none the game repo found, so callers derive it from two reads (`ShipSpeed`).
- **Orders** (engine thread only; one ship per command, a one-ship `Selection` of our own; every check before the first call):
  `OrdersShipMove(ship, ShipMoveArgs{x, z, heading, sail, queue})` builds the target with the engine's ship location call (no y) and
  pushes the ship move command carrying the sail; a heading is a queued facing order after it (the move has none).
  `OrdersShipFace(ship, heading, flag, queue)` (the engine's rotate command; `flag` is its own, meaning in the game's facts) and
  `OrdersShipHalt(ship)`. A ship the engine's AddShip refuses (routing, sinking) is refused with the count it took.
- **Lua**: `wsp.ship_state`, `ship_list`, `ship_selection`, `ship_move(ref, x, z, [heading], [sail], [queue])`, `ship_face`,
  `ship_halt` (`luabridge.cpp` header). A number ref is the n-th ship of the cached fleet.
- **Checked result** (`CheckShipArrival`, `ShipSettled`; C17): a live reading against the ordered target, heading and sail, and that
  the ship moved at least `minMoveFrac` of the distance asked; settled when two reads `dt` apart give less than `settleSpeed` m/s and
  `settleTurn` deg/s. The thresholds are the game's measured numbers (its route block), not the defaults in `ships.h`.
- **Adapter**: site ids and operand offsets (checked by `proxy/tests/test_ships.cpp` against the generated table), the command size,
  the move's default sail and mode, the engine's four sail values and its level thresholds.
