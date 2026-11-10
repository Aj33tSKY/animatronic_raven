# Assembling the crow

How to put the printed crow together. This is the mechanical part of the original
[Animatronic Crow build guide](https://github.com/swaziloo/halloween/blob/main/animatronicCrow/BUILD.md)
by Ken Goudey (swaziloo), trimmed for Wraven. The electronics live outside the crow on a
breadboard instead of the Creature Control PCB, so the PCB, sound-board and motion-sensor
steps are gone; see [hardware.md](hardware.md) for parts, wiring and calibration.
Printing: see [../model/README.md](../model/README.md).

## Parts for the crow

![Crow parts everywhere](images/AniCrow030.jpg)

| Qty | Part | Note |
|-----|------|------|
| 2 | 5mm red LEDs | For the eyes. Frosted look best. |
| 1 | SG90 5V servo | MG90S also works. |
| 1 | 28BYJ-48 5V stepper | With its ULN2003 driver board. |
| 1 | 40mm 4Ω, 3W speaker | 8Ω works. Consider a waterproof speaker if the crow will live outdoors. |
| 3 | M2.6 × 10mm tapping screws | For the speaker flange. |
| | Wires | Long enough to reach from the crow, out through the tail, to the breadboard: 2-wire for the LEDs and speaker, 3-wire for the servo; the stepper has its own cable. |
| 1 | Large paperclip | About 1.25mm thick. |
| 1 | 2mm rod | About 15mm long, for the beak hinge. Carbon fibre or any 2mm material. |
| 7 | M3 × 4 × 5 heat-set inserts | 5mm-tall (M3 × 5 × 5) inserts also fit. |
| 9 | M3 screws | 5 × 8mm for the head and tail, 2 × 6mm for the stepper, 2 × 5mm countersunk for the body (regular 6mm work too). |
| 2 | M3 nuts | For the stepper collar in the head. |
| 8 | 10 × 3mm magnets | Neodymium, for attaching the tail. |
| | CA glue and/or epoxy | For the feet and magnets. |
| | Hot glue | For sealing the speaker wire (and optionally the speaker). |
| | Polyfill | A little, for damping inside the speaker box. |

---

## Head

| | |
|---|---|
| ![LEDs for crow eyes](images/AniCrow017.jpg) | Begin with the LEDs. Their resistor goes on the breadboard, so just wire the two LEDs in parallel. A 2-wire lead with its connector cut off, a couple of short pieces of high-temperature wire and some heat-shrink tubing work well. |
| ![Soldered LEDs for crow eyes](images/AniCrow016.jpg) | Solder the LEDs together "stacked", joining the positive (long) legs to one wire and the negative legs to the other. Cover all exposed wiring with heat-shrink or electrical tape. |
| ![Crow LED eyes test](images/AniCrow015.jpg) | Before assembling, test them: wire them to the breadboard (Nano D3 → 1kΩ → LEDs, see [hardware.md](hardware.md)) and type `E4` in the Serial Monitor. Both should light evenly. |
| ![Crow LED eyes installed](images/AniCrow014.jpg) | Carefully bend and fit both eyes into the sockets so the cables lie nicely and run down the back inside of the head. Set them to a depth that looks right (don't push them all the way in). |
| ![Crow LED eyes glued](images/AniCrow013.jpg) | With everything in place, lock in the eyes and cable connections with hot glue, and leave it to cool completely. |
| ![Crow actuator parts](images/AniCrow067.jpg) | The actuator is made from four small parts. Print these with a 0.2mm nozzle for strength and accuracy. The metal pieces are cut from a large (~1.25mm) paperclip. |
| ![Actuator hinge pin](images/AniCrow065.jpg) | The beak's hinge pin needs to be 21.5mm long (21 to 21.6mm is fine) with smooth, rounded ends. If you can, use a micrometer and a small grinder or file to get the length right and round the ends. |
| ![Actuator servo connection](images/AniCrow068.jpg) | Bend a second ~20mm piece (also with rounded ends) into a sharp 90-degree angle. The tighter the better. |
| ![Assembled actuator](images/AniCrow066.jpg) | The assembled actuator looks like this. The 90-degree piece should snap into place, but a touch of glue won't hurt. |
| ![Insert the left side of the actuator pin](images/AniCrow064.jpg) | Fitting the actuator into the beak needs a firm hold, because you have to flex the plastic. Start by putting the long (left) side into its hole as shown. |
| ![Flex the beak and swing the right side into place](images/AniCrow063.jpg) | While pushing down with the actuator and flexing the right side of the beak up (away), pivot the pin into the second hole. |
| ![Crow beak hinge pin install](images/AniCrow012.jpg) | Cut the 2mm rod just longer than the support and round the ends. It's a little easier to press it through from the right side. Be careful not to bend the tower tabs; they're somewhat delicate. |
| ![Beak and actuator attached to servo mount](images/AniCrow062.jpg) | The assembled beak, servo plate and actuator should move freely. Add dry lubricant to the beak hinge pins and to the side of the mount where the actuator slides. (The actuator won't hit the hinge pin.) |
| ![Reset the servo position](images/AniCrow085.png) | Wire the servo to the breadboard ([hardware.md](hardware.md)), power up, and in the Serial Monitor type `U1000` to move the servo to the 1000 position. Then unplug the power and the servo and carry on. |
| ![Attach servo arm at lowest position](images/AniCrow061.jpg) | Install the servo with its wires towards the plate, using the two screws that came with it. Hold the beak all the way down, put the spacer on the actuator pin, and hook the single servo arm over it at the second-to-last hole. Slide the arm onto the servo gears as low as it will go without hitting the plate or putting the gears under tension. Install the screw. |
| ![Validate the ranges in software](images/AniCrow086.png) | Screw the servo plate to the head with a couple of M3 screws, reconnect, and find the beak's fully open and fully closed values with the `U` command, then save them in the firmware. See "Calibrate" in [hardware.md](hardware.md). |
| ![Consider thread locker on head collar screws](images/AniCrow076.jpg) | Consider thread locker on the stepper collar's mounting screws: clean the screws and nuts with isopropyl alcohol, then add a little removable thread locker to the threads. |
| ![Install mounting screws into stepper collar](images/AniCrow024.jpg) | Sand the sliding arc on the inside of the stepper collar smooth and add dry lube. Drop two M3 nuts into the slots, and fit two 8mm M3 screws using a hex key through the access holes, until they just touch the stepper pin. |
| ![Assembly](images/AniCrow001.jpg) | Once everything looks good, route the cables through the plates, stack the parts, and join them with two M3 × 8mm screws. The head is ready. |

---

## Body

| | |
|---|---|
| ![Crow body components](images/AniCrow032.jpg) | The body parts. |
| ![Install M3 heat melt inserts](images/AniCrow031.jpg) | Install five heat-set inserts in the body: two for the stepper plate, two for the stepper, and one for the tail tab. (The original's two PCB-rail inserts aren't needed.) |
| ![Glue on the feet](images/AniCrow038.jpg) | Glue on the feet. Slow-curing two-part epoxy works well: coat the sockets and pegs, stand the crow upright on a flat surface, and press down lightly on the body to settle the feet before leaving it to set. |
| ![Glue on the magnets](images/AniCrow082.jpg) | Remove the supports and scrape the magnet recesses clear. Glue the magnets in with epoxy or CA, paying close attention to polarity. |
| ![Add the tab to the tail](images/AniCrow051.jpg) | The tail tab snaps into place; you may need to press hard until it clicks. |
| ![Tail tab installed](images/AniCrow033.jpg) | With the tab installed, the tail is ready. |
| ![Prepare the speaker](images/AniCrow034.jpg) | Attach the lead to the speaker: solder the two wires directly to it. Make the lead long enough to reach the amplifier outside the crow. Once the speaker is glued in, there shouldn't be any strain on the wires. |
| ![Add glue to the speaker wire pass-thru](images/AniCrow078.jpg) | Feed the speaker wires through the guide ring on the side of the speaker box. A little loose polyfill in the box reduces rattle (leave it out if the crow will be outside in the wet). Seal the wires into the slot with hot glue. |
| ![Install the speaker and seal the wires](images/AniCrow079.jpg) | Seat the speaker, then top up the glue around the wires so sound can't leak. |
| ![Install the speaker ring with screws](images/AniCrow080.jpg) | Fix the speaker flange with the M2.6 tapping screws, or glue the speaker into its housing. |
| ![Prepare the stepper mounting plates](images/AniCrow046.jpg) | The head rotates on the two pegs just to the sides at the bottom of the stepper mount. Sand these, and the sweeping arc on the head's stepper collar, to 800 grit and coat them with dry PTFE lubricant. |
| ![Mount the stepper to the plate](images/AniCrow069.jpg) | Mount the stepper with two M3 × 6 screws. |
| ![Route the stepper wire through the ring](images/AniCrow045.jpg) | Routing the stepper cable needs long needle-nosed pliers: bend the wires sideways and slip the connector and wires through the same ring as the speaker wires. |
| ![Attach the stepper plate](images/AniCrow040.jpg) | Attach the stepper plate to the body with the M3 countersunk screws. |
| ![Attach the head](images/AniCrow039.jpg) | Fit the head onto the stepper, using a piece of card stock to shim the top edge. With a 2mm hex key through the access holes on each side, tighten the two collar screws alternately: first both just snug, then both firm. They're what make the head turn with the motor, so make sure they're tight. Then power up with the head on, so the neck finds its centre against the end stop (see "Neck" in [hardware.md](hardware.md)). |
| ![All the wires out of the back](images/AniCrow052.jpg) | All the wires (eyes, servo, stepper and speaker) should now be hanging out of the back of the body. Route them out through the hole in the tail to the breadboard and amplifier, which sit outside the crow. |
| ![Attach the tail](images/AniCrow056.jpg) | Attach the tail to the back of the crow; the magnets hold it. |
| ![Secure the tail tab with a M3 screw](images/AniCrow055.jpg) | If you like, secure the tail with an M3 × 8 screw through the hole between the wings, just in front of the tail. |
