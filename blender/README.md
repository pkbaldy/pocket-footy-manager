# Blender assets

Source files for the art rendered into `index.html`. The game embeds the rendered
images, so nothing here is loaded at runtime. These files are for editing and re-rendering.

| File | What it is |
|---|---|
| `footy_player.blend` | Low-poly AFL player. Frames 1–8 run cycle, 9 standing, 11+ action poses (kick, handball, mark, tackle, ruck tap, celebrate). |
| `sherrin.blend` | The ball. Frames 1–8 drop punt (end over end), 9–16 torpedo (spiral). |
| `ground_div1.blend` … `ground_div4.blend` | Aerial home grounds: 1 National, 2 State, 3 Country, 4 Outback. |
| `foil_pack.blend` | Foil card pack for the Pack Shop (the game renders one per pack colour). |
| `scripts/footy_player.py` | Builds the player and renders the colour + kit-data sprite sheets. |
| `scripts/sherrin.py` | Builds and renders the ball strip. |
| `scripts/grounds.py` | Builds and renders each ground plus its seat mask (seats are tinted to the home club in game). |
| `scripts/packs.py` | Builds and renders a foil pack in a given colour. |

Re-render (Blender 4.5+):

```
blender --background --python scripts/footy_player.py -- out 96
blender --background --python scripts/sherrin.py -- ball 48
blender --background --python scripts/grounds.py -- grounds 1.4 4321
blender --background --python scripts/packs.py -- packs forwards 0.85,0.10,0.08 420
```

Jumpers, shorts and socks are rendered white, with a separate kit-data pass
(R = height, G = angle around the body, B = garment). The game paints each club's
colours and jumper style onto them per pixel.
