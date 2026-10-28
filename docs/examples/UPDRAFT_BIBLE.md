# Updraft: production bible

Generated from `samples/updraft/production.json`, the single source of the ZeroField showcase. Content is CC0 1.0.

## Logline

Over a red canyon at sunrise, a trainee pilot's burner dies on her first solo flight; her instructor refuses to take the controls, and she has seconds to relight it before the balloon hits the wall.

## Brief

### Production Brief

- Format: one scene, ten shots, about forty seconds, 16:9
- Cast: @CAST-01 Noa, the trainee pilot; @CAST-02 Ines, her instructor
- Locations: @SET-01 the canyon at sunrise, @SET-02 the canyon rim, @SET-03 inside the basket, @SET-04 inside the envelope
- Props: @PROP-01 the balloon, @PROP-02 the basket, @PROP-03 the burner (states @PROP-03:lit and @PROP-03:dead), @PROP-04 the flint striker
- Look: 35mm film body, low sunrise, one sun and one flame as the only lights
- Pacing: hold the geography, lose the flame, hold the silence, burst into the sun

### The scene

The balloon drifts toward the canyon's north wall. Noa fires the burner; Ines watches her hands. The flame coughs and dies. The balloon sinks past the shadow line toward the rock. Noa says the pilot light is out. Ines moves her hand toward the valve, stops, and says two words: "Your balloon." Noa strikes the flint by hand, three times. The burner roars into the envelope, the balloon clears the rim by a few metres and rises into full sun. Noa laughs out a breath; Ines looks away so Noa will not see her smile.

### How this production is built

- **Assets first.** Every character, place and prop is a locked description plus pictures before any shot is generated. Characters have a three-view sheet: a 3/4 face close-up, a full-body front with no head, and a full-body back, on neutral grey with flat light.
- **One job per reference.** The face comes only from the face close-up, the clothes from the body, the space and materials from the location plate, the shape from the prop photo. Every prompt says what each picture is for.
- **Every state is its own asset.** The burner lit and the burner dead are separate assets with their own pictures.
- **Locks pasted word for word.** Location map, the single light logic, voice and acting profiles live on the assets and go into every shot unchanged.
- **Behaviour, not emotion.** Each shot is written as timed physical beats; fear is the eyes reaching the wall before the head turns, not the word "afraid".

### Production Notes

All media in this production were generated with open-weights models (FLUX 3 Klein for assets and first frames, LTX-2.5 for video and sound) through ComfyUI. The generation record of every picture and take is kept with it.


## Episode look

Camera: film-35mm, auto-lens, f4. Genre: distant-miles. Era: grain-film. Light: low-sun. Tempo: auto. Palette: auto.

## Cast

### CAST-01 Noa

A slight, wiry woman with a sun-browned oval face, dark straight eyebrows, a straight nose with a small bump on the bridge, a thin pale scar crossing her left eyebrow, and short blunt black hair cut at the jaw and tucked behind both ears. She wears a faded saffron-orange flight jacket open over a heather-grey hoodie, sleeves pushed to the forearms, tan canvas work trousers, scuffed brown leather boots, and thin brown leather gloves with the fingertips cut off. seed: 21001

**Voice.** Young female voice, light and quick, slightly hoarse from the dry morning air; speaks fast and low when she is nervous, words clipped short; when she is frightened the breath comes before the word.

**Acting profile.** NOA — compact body, weight on the balls of her feet, shoulders creeping up toward her ears when she concentrates. She wants to prove she can fly alone and is terrified of being the one who freezes. Habits: checks the envelope and the canyon wall every few seconds even when nothing has changed; runs her thumb along the red valve handle; bites the inside of her cheek. Under pressure her hands get fast and imprecise and her eyes dart between the burner, the wall and Ines. However, when Ines says nothing and only looks at her, Noa's hands slow down and become exact.

*Note:* Trainee pilot. Lock the face before any shot; stress-test her next to CAST-02 inside SET-03.

### CAST-02 Ines

A tall, broad-shouldered woman with a weathered, deeply tanned face, deep crow's feet, heavy dark eyebrows, a nose that healed slightly crooked, and silver-grey hair pulled back into a short thick braid. She wears an olive-green quilted vest over a navy cable-knit wool sweater, dark grey cargo trousers, black leather boots, and aviator sunglasses pushed up into her hair. seed: 21002

**Voice.** Low, dry, unhurried female voice with a faint gravel and a soft Iberian accent; she never raises it, and the worse things get the slower she speaks.

**Acting profile.** INES — planted wide, one hand resting on the basket rim, weight in her heels. She wants Noa to save the balloon herself and is ready to take over only at the last possible second. Habits: watches the student's hands, never her face; taps the rim once with her thumb when she disapproves. Under pressure she becomes stiller and breathes slower; the only sign is her hand moving a few centimetres toward the valve and stopping. However, when Noa gets it right, one corner of her mouth goes up and she looks away to the canyon to hide it.

*Note:* Flight instructor. Radically different silhouette from Noa: tall, silver braid, olive vest.

## Locations

### SET-01 The Canyon at Sunrise

A deep red sandstone canyon at sunrise: sheer walls layered in rust, ochre and pale cream bands, wind-carved ledges, a thin green river far below on the canyon floor, and one free-standing flat-topped sandstone spire rising apart from the north wall. Long cool shadow fills the lower canyon while the upper walls and rims glow gold. seed: 21011

**Voice.** Wind moving through the canyon, a distant river, an occasional falling pebble.

**Location map.** GEO LAYOUT — The canyon runs away from camera toward the sunrise. NORTH WALL: frame-right, sheer, its base in blue shadow. THE SPIRE: a free-standing flat-topped column about sixty metres out from the north wall, mid-right. SOUTH RIM: frame-left, lower, sunlit. THE RIVER: a thin line on the canyon floor far below. The balloon drifts from frame-left toward the north wall. The camera always stays on the south side and never crosses to the north wall's side.

**Light logic.** One sun only: a low sunrise at the far end of the canyon, slightly frame-left, raking along the walls. Everything above the shadow line is warm gold and everything below it is cool blue shade; the shadow line sits about halfway down the north wall. The burner flame is the only other light, and only while it fires. Palette: 60% rust and ochre rock, 30% deep morning-blue sky and shade, 10% saffron-orange balloon.

*Note:* Master location. The spire is the anchor every exterior shot is placed against.

### SET-02 The North Rim

The flat top of a red canyon's north rim in early sun: wind-cut sandstone slabs, low silver sagebrush, two twisted juniper trees near the edge, the far rim of the canyon visible across the gap, and an open pale-blue sky. seed: 21012

**Voice.** Wind over open rock, juniper branches stirring.

**Location map.** GEO LAYOUT — The rim edge runs left to right across the lower third of the frame; the drop into the canyon is in front of it, toward camera. Two juniper trees stand on the rim at frame-right. The far rim sits on the horizon line. The camera is in the air beyond the edge, level with the rim top, looking across it.

**Light logic.** One sun only: low and behind camera-left. The rim top is fully lit warm gold; the canyon below the edge falls into cool blue shade. Palette: 60% rust and ochre rock, 30% pale morning-blue sky, 10% saffron-orange balloon.

*Note:* Where the balloon clears the edge.

### SET-03 Inside the Basket

The inside of a hot-air balloon basket in flight: chest-high walls of pale woven willow, a padded tan leather rim, four padded corner uprights rising to a steel burner frame overhead, two steel fuel cylinders in blue cloth covers strapped in opposite corners, a coil of rope, and open air beyond the rim above a red canyon. seed: 21013

**Voice.** Wicker creaking, cables ticking, wind across the rim, the burner's roar when it fires.

**Location map.** BASKET MAP — about 1.4 by 1.2 metres. The burner hangs overhead at the centre. Noa stands at the burner, frame-left of centre, right hand on the red valve. Ines stands in the far right corner, her back to the upright, one hand on the rim. Fuel cylinders: far-left corner and near-right corner. The canyon's north wall lies beyond the rim at frame-right. The camera hovers just outside the near rim and never crosses to the far side of the basket.

**Light logic.** The low sun comes from frame-left and behind: warm light on the left side of both faces and a gold rim on hair and shoulders, the right side of the faces in soft shade. When the burner fires, warm orange light falls from directly above onto heads and shoulders.

*Note:* The corner every dialogue beat is staged in: give the model the basket, not the sky.

### SET-04 Inside the Envelope

Looking straight up through the mouth of a hot-air balloon into its hollow envelope: tall fabric gores in saffron-orange and deep teal converge toward a round crown opening of pale sky far above, dark load tapes run up every seam, and the fabric glows from within. seed: 21014

**Voice.** The deep hollow hum of air inside a large fabric dome.

**Location map.** GEO LAYOUT — The mouth of the envelope frames the bottom of the image; the gores converge to the crown at top centre; the twin burner coils sit at the bottom centre of the frame, close to camera.

**Light logic.** The sun shines through the fabric from frame-left so the orange gores glow; when the burner fires, its flame lights the whole interior warm orange from below.

*Note:* For the relight.

## Props

### PROP-01 The Balloon

A hot-air balloon in flight: a smooth teardrop-shaped envelope of vertical fabric gores alternating faded saffron-orange and deep teal with one cream gore, slightly sun-bleached, a small patch near the mouth, and a rectangular wicker basket hanging below on steel cables. seed: 21021

**Shape lock.** A smooth teardrop envelope about twenty metres tall; vertical gores alternating saffron-orange and deep teal with exactly one cream gore; plain unbranded fabric; one small rectangular wicker basket on four cables far below the envelope.

*Note:* Exterior shots only.

### PROP-02 The Basket

A rectangular hot-air balloon basket: woven pale willow, chest high on a standing adult, a padded tan leather rim, four padded corner uprights rising to a square steel burner frame, and steel cables running up from each corner. seed: 21022

**Shape lock.** A rectangular wicker basket, chest-high, with a leather-padded rim, four padded corner uprights and exactly two fuel cylinders inside.

### PROP-03 The Burner

A twin hot-air balloon burner: two round coils of stainless steel tubing side by side on a square frame, the coils blackened by heat, two red-handled blast valves hanging beneath, and flexible black fuel hoses looping down. seed: 21023

**Shape lock.** Two round coiled burners side by side with blackened steel coils and two red-handled valves beneath; it hangs above head height at the centre of the basket.

*Note:* Two states: PROP-03:lit and PROP-03:dead.

### PROP-04 The Flint Striker

A hand-held flint striker for a gas burner: a short steel rod with a spring-loaded cup-shaped flint head at one end and a worn black rubber grip, on a coiled cord. seed: 21024

**Shape lock.** A palm-sized steel striker with a cup-shaped head and a black rubber grip, held in the fist like a short tool; scraping it throws a shower of small bright sparks.

### Prop states

- **PROP-03:lit** (The Burner — firing, STATE of @PROP-03): Both coils are firing: a tall roaring flame about one and a half metres long, blue at the root and yellow-orange above, with heat shimmer around it.
- **PROP-03:dead** (The Burner — cold, STATE of @PROP-03): The burner is cold: the coils are dark and dull, with no flame and no pilot light.

## Shot list

### S01 The balloon over the canyon

- Optical rig: Cinema camera / 24mm wide
- Camera motion: Static — the camera stays put on the south rim

```text
0.0–1.0s — @PROP-01 hangs small in the upper third, mid-left, drifting toward the spire of @SET-01; the canyon floor lies in blue shade and the walls above the shadow line glow gold.
1.0–3.0s — the balloon drifts slowly toward the north wall; a long burst of burner flame flares under the envelope and fades.
3.0–4.0s — the balloon keeps drifting; its small shadow slides across the sunlit north wall.
PHYSICS: the balloon moves slowly and heavily, swaying a little under the envelope; haze hangs in the low sun.
CHECK: the balloon reads tiny against the canyon; the spire stands many times taller than the whole balloon.
ORDER: hold → burner flare → drift toward the wall.
```

*Director note:* The first second holds the geography: spire mid-right, north wall frame-right, sun at the far end.

### S02 The burn

- Optical rig: Cinema camera / 35mm
- Camera motion: Handheld — floating just outside the near rim, small human drift

```text
0.0–1.0s — @CAST-01 stands at the burner, frame-left of centre, right hand already pulling the red valve; @PROP-03:lit roars overhead; @CAST-02 stands in the far right corner of @SET-03, back to the upright, one hand on the rim, watching Noa's hands.
1.0–3.0s — Noa releases the valve and the flame drops; she glances down over the rim at frame-right, then back up at the envelope; her shoulders are up near her ears.
3.0–4.0s — Ines's thumb taps the rim once; her eyes stay on Noa's hands.
PHYSICS: heat shimmer above the basket while the burner fires; the basket creaks and sways a few degrees; collars lift in the heat.
CHECK: exactly two people in the basket: the small one in orange at the burner and the tall one with the silver braid in the far corner.
ORDER: burn → release → glance → tap.
```

*Director note:* Two-shot that fixes who stands where for the rest of the scene.

### S03 The flame dies

- Optical rig: Cinema camera / 85mm close-up
- Camera motion: Static — the camera stays put

```text
0.0–1.5s — close on @PROP-03:dead above head height: the last of the flame shrinks, coughs once and goes out; the twin coils stand dark.
1.5–4.0s — the gloved right hand of @CAST-01 enters from frame-left and squeezes the red valve twice; nothing lights; a thin hiss of gas, then silence.
PHYSICS: the dark coils tick as they cool; a faint wobble of hot air fades above them.
CHECK: only her gloved hand and forearm are in frame; the burner keeps its exact shape: two round coils side by side, two red-handled valves beneath.
ORDER: flame dies → hand squeezes → nothing.
```

*Director note:* Insert. The silence after the hiss is the beat.

### S04 The pilot is out

- Optical rig: Cinema camera / 85mm close-up
- Camera motion: Static — the camera stays put, slight handheld breathing

```text
0.0–1.0s — @CAST-01 in close-up, face toward camera and tilted up to the cold burner above frame, right hand still on the valve below frame; @CAST-02 is a soft out-of-focus shape in the far corner of @SET-03 behind her.
1.0–2.5s — her eyes reach the canyon wall at frame-right before her head turns; one quick double-blink; she bites the inside of her cheek; the jaw sets once.
2.5–4.0s — the breath comes before the words; she speaks fast and low, to the burner and not to Ines: "It's out. The pilot's out."
PHYSICS: the basket sinks and sways a few degrees; strands of her black hair lift in the rising air.
CHECK: her face stays the face of @CAST-01, with the scar through the left eyebrow and the bump on the nose; Ines stays soft and small behind her.
ORDER: eyes up → eyes to the wall → double-blink → the line.
```

*Director note:* Front-facing, visible fear written as behaviour. The hardest shot of the scene.

### S05 Sinking toward the wall

- Optical rig: Cinema camera / 200mm telephoto
- Camera motion: Static — the camera stays put far across the canyon

```text
0.0–1.0s — @PROP-01 hangs in the middle of the frame, sinking, the sheer north wall of @SET-01 filling the frame behind it, the shadow line crossing the rock just above the basket.
1.0–4.0s — the balloon keeps sinking past the shadow line into the blue shade; its own shadow on the rock grows and closes on it; the spire stands at frame-right.
PHYSICS: the envelope sags a little as it cools; the basket swings gently under it.
CHECK: the wall fills the frame from top to bottom and the balloon is small against it; there is no flame under the envelope.
ORDER: hold → sink past the shadow line → the shadow closes in.
```

*Director note:* Telephoto compression makes the wall loom.

### S06 Your balloon

- Optical rig: Cinema camera / 85mm close-up
- Camera motion: Static — the camera stays put

```text
0.0–1.5s — @CAST-02 in close-up in the far corner of @SET-03, face toward camera, sunglasses pushed up into her silver hair; her eyes are on Noa's hands below frame, never on Noa's face; her right hand rests on the rim.
1.5–3.0s — her hand slides a few centimetres along the rim toward the valve, and stops; she breathes out slowly through her nose.
3.0–4.0s — low and slow, moving nothing else, she says: "Your balloon."
PHYSICS: the sinking basket sways; the low sun rakes across her face from frame-left; a loose strand of grey hair moves in the air.
CHECK: her face stays the face of @CAST-02, with the crooked nose, deep crow's feet and silver braid; @CAST-01 is a soft orange shape at the frame-left edge.
ORDER: eyes on the hands → the hand moves and stops → the line.
```

*Director note:* Stillness as held tension. The hand that stops is the accent.

### S07 The striker

- Optical rig: Cinema camera / 100mm macro
- Camera motion: Static — the camera stays put

```text
0.0–1.0s — the gloved right hand of @CAST-01 is already mid-strike, scraping @PROP-04 up against the underside of the dark coil of @PROP-03:dead; a shower of bright sparks.
1.0–2.5s — a second strike: more sparks spray and die against the cold steel.
2.5–4.0s — a third strike: the sparks catch and a small blue flame blooms at the coil.
PHYSICS: the sparks fall in short bright arcs and die in the air; the hand shakes slightly between strikes.
CHECK: one gloved hand with five fingers holds the short steel striker; the coil keeps its round shape.
ORDER: strike → strike → catch.
```

*Director note:* A state, not a process: the strike is already happening in frame one.

### S08 The roar

- Optical rig: Cinema camera / 18mm ultra-wide
- Camera motion: Static — the camera stays put, looking straight up

```text
0.0–1.0s — looking straight up from the basket into @SET-04: the gores converge to the bright crown far above; the twin coils of @PROP-03:lit sit close at the bottom of the frame with a small blue flame at one coil.
1.0–2.0s — the burner opens: a roaring yellow-orange flame shoots a metre and a half up into the mouth of the envelope.
2.0–4.0s — the whole interior lights up warm orange like a lantern; heat shimmer ripples the fabric; the flame keeps roaring.
PHYSICS: the flame is loud, wide and heavy, blue at the root and yellow-orange above; the fabric breathes outward as the air heats.
CHECK: the flame stays well below the fabric; the gores keep their orange and teal colours.
ORDER: small flame → roar → the interior glows.
```

*Director note:* The VFX shot of the film.

### S09 Clearing the rim

- Optical rig: Cinema camera / 50mm
- Camera motion: Static — the camera stays put, level with the rim

```text
0.0–1.0s — the sunlit rim of @SET-02 runs across the lower third; the top of the basket of @PROP-01 is just visible below the edge in blue shade, the envelope above it glowing.
1.0–3.0s — the balloon rises: the basket climbs past the rim edge with only a few metres to spare, the junipers at frame-right passing just beneath it.
3.0–4.0s — the basket rises out of the shadow into full gold sunlight under a long burst of flame.
PHYSICS: the balloon rises slowly and heavily; the juniper branches stir in the downdraft.
CHECK: the basket clears the rim; the balloon keeps its saffron-orange and teal gores.
ORDER: basket below the edge → rises past the rim → into the sun.
```

*Director note:* The release.

### S10 In the sun

- Optical rig: Cinema camera / 35mm
- Camera motion: Handheld — floating just outside the near rim, small human drift

```text
0.0–1.5s — full gold sun on the basket; @CAST-01 at the burner, frame-left, right hand still on the red valve, her chest heaving; @CAST-02 in the far right corner of @SET-03.
1.5–3.0s — Noa breathes out hard and a short laugh breaks out of the breath; her hand stays on the valve.
3.0–4.0s — Ines looks away to the canyon at frame-right; one corner of her mouth goes up.
PHYSICS: both chests rise and fall; warm wind lifts Noa's hair; the basket steadies.
CHECK: exactly two people: Noa small in orange at the burner, Ines tall with the silver braid in the far corner.
ORDER: sun → Noa's laugh → Ines looks away and smiles.
```

*Director note:* The emotion stays in the breath and the look away.

## Why it is built this way

- **Assets first.** Every character, place and prop is a locked description plus pictures before any shot is generated. A character has a three-view sheet: a 3/4 face close-up, a full-body front with no head, and a full-body back, on neutral grey with flat light.
- **One job per reference.** The face comes only from the face close-up, the clothes from the body, the space and materials from the location plate, the shape from the prop photo. Every prompt says what each picture is for.
- **Every state is its own asset.** The burner lit and the burner dead are separate assets with their own pictures and a one-line change from the base.
- **Locks pasted word for word.** The location map, the single light logic, voice and acting profiles live on the assets and go into every shot unchanged.
- **Behaviour, not emotion.** Each shot is written as timed physical beats; fear is the eyes reaching the wall before the head turns, not the word "afraid".
- **Stress-test before shooting.** Each asset must stay recognisable in other poses, other light and next to the other assets.
- **Open weights only.** FLUX 3 Klein makes the assets and first frames, LTX-2.5 the video and sound, through ComfyUI; the generation record of every picture and take is kept with it.
