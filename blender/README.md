# Blender assets

Source files for the art rendered into `index.html`. The game embeds the rendered
images, so nothing here is loaded at runtime. These files are for editing and re-rendering.

| File | What it is |
|---|---|
| `footy_player.blend` | Stylised AFL player (hair, face, boots, collar/armhole trim, back number). Frames 1–12 run cycle, 13–16 idle, then action poses (kick, handball, mark, tackle, ruck tap, celebrate). Skin, hair and boots are tinted per player in game. |
| `sherrin.blend` | The ball, with pebbled grain, raised seams and a maker's stamp. Frames 1–8 drop punt (end over end), 9–16 torpedo (spiral). Rendered at 96px, shrunk to 48px. |
| `ground_div1.blend` … `ground_div4.blend` | Aerial home grounds, each with its own landmarks: 1 National (two tiers, corporate boxes, canopy), 2 State (heritage stand, the hill, tram), 3 Country (netball court, clubrooms, pine windbreak), 4 Outback (windmill, dam, sheep, tin shed). |
| `ground_div0_oculus.blend` | Worlds Division: the Oculus, a glass ring roof over a two-tier bowl. The roof is rendered as a separate see-through overlay. |
| `foil_pack.blend` | Foil card pack for the Pack Shop, with an embossed footy and a holo strip (the game renders one per pack colour). |
| `scripts/footy_player.py` | Builds the player and renders the colour + kit-data sprite sheets. |
| `scripts/sherrin.py` | Builds and renders the ball strip. |
| `scripts/grounds.py` | Builds and renders each ground plus its seat mask (seats are tinted to the home club in game). |
| `scripts/packs.py` | Builds and renders a foil pack in a given colour. |
| `scripts/icons.py` | The game's icon set (replaces emoji): writes the SVG sprite and the emoji → icon map. Plain Python, no Blender. |

Re-render (Blender 4.5+):

```
blender --background --python scripts/footy_player.py -- out 96
blender --background --python scripts/sherrin.py -- ball 48
blender --background --python scripts/grounds.py -- grounds 1.4 4321
DOME=oculus blender --background --python scripts/grounds.py -- grounds 1.4 0
blender --background --python scripts/packs.py -- packs forwards 0.85,0.10,0.08 420
```

Jumpers, shorts and socks are rendered white, with a separate kit-data pass
(R = height, G = angle around the body, B = garment). The game paints each club's
colours and jumper style onto them per pixel.
