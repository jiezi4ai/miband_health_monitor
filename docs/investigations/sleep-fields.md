**English** · [简体中文](sleep-fields.zh-CN.md)

# Investigation conclusions on the three bytes at the end of activity records

> **De-identification note**: the dates in this document are all placeholder dates (uniformly mapped
> to January 2020) and serve only to distinguish nights and their relative order; they do not
> represent real collection times. The listed values are aggregate statistics and contain no device
> identifiers, accounts or per-minute raw samples.

> Conclusion first: **the names `sleep / deep_sleep / rem_sleep` are wrong.** They are neither the
> per-minute sleep duration nor sleep stage codes. The evidence follows (all from a real Mi Band 6,
> 1920 minute samples).

## 1. The field offsets are right; the names are wrong

The real device layout of 8 bytes/minute is exactly the same as Gadgetbridge's `HuamiExtendedActivitySample`:

| Offset | Field | Description |
|---|---|---|
| 0 | `kind` | The band's own activity state machine, see §3 |
| 1 | `intensity` | Activity intensity 0–149 |
| 2 | `steps` | Steps in that minute 0–116 |
| 3 | `heart_rate` | Heart rate for that minute, `255` = no measurement |
| 4 | `unknown1` | 0–63, 12 distinct values, semantics unknown |
| 5 | `sleep` | 0–62 |
| 6 | `deep_sleep` | Always ≥128 (`0x80` set), effective value 0–64 |
| 7 | `rem_sleep` | Always ≥128 (`0x80` set), effective value 0–78 |

The offsets are correct, so the parser does not need changing; what is wrong is treating 5/6/7 as
"durations".

## 2. Why they are not sleep durations

1. **Not monotonic.** If they were "how long I have slept so far tonight", they would have to rise
   monotonically to 300+ minutes over the night. The actual values oscillate between 13–68 all
   night, with a maximum of only 68.
2. **They are smooth analog quantities, not discrete stages.** The average change between adjacent
   minutes is only 1.21 / 2.34 / 2.83, with a maximum of 31–60 — these are continuous values after
   filtering, not stage codes of 0/1/2/3.
3. **The bit-packing hypothesis does not hold.** Looking at the distribution in 2-bit groups, the
   top two bits of `deep_sleep` are `10` in all 1073/1074 cases (i.e. `0x80` is constant) and the
   remaining bits are spread evenly; there is no structure of "one stage per 2 bits".
4. **They only have values in specific states.** In the 679 minutes with `kind=243`, `deep/rem` are
   100% 0x80; in the 330 minutes with `kind=240`, 99.7% are non-zero. That is, whether these two
   bytes have values depends on the low 2 bits of `kind`.

Point 4 is the most interesting and the most telling: on the same night, the first half
(`kind=240`, 330 minutes) has values while the second half (`kind=243`, 461 minutes) is all zeros.
**Across two consecutive nights, the first night had values for 463 minutes and the second night
had values for 0 minutes.**

Speculation (unverified): these two bytes are a cache of the band-side "sleep staging result",
written only after some internal state completes, or requiring "scientific sleep monitoring" to be
enabled on the Zepp App side. Since we never run Zepp, the second night may stay at 0x80 (= 0)
because staging has not been computed yet.

**So we cannot claim they are deep-sleep/REM durations; hard-coding a fitted mapping would repeat
this project's earlier IMU mistake where "the simulator and the parser shared the same wrong
assumptions".**

## 3. `kind` is the usable sleep signal

`kind` is the output of the band's own state machine; 27 distinct values appear across 1920 minutes,
and the bit-level structure is clear:

| kind | Bit pattern | When it appears | Characteristics |
|---|---|---|---|
| 240 | `1111 0000` | all night | sleep, `deep/rem` bytes have values |
| 249/250 | `1111 1001` / `1111 1010` | briefly at night | transitions during sleep |
| **243** | `1111 0011` | **679 minutes across the night** | **not worn** (see §6), not sleep |
| 112 | `0111 0000` | at night, before sleep onset | still |
| 80 | `0101 0000` | daytime sitting / awake at night | still |
| 96 | `0110 0000` | daytime | still |
| 1 / 16 / 17 | `0000 0001` / `0001 0000` / `0001 0001` | daytime | walking (steps obvious) |
| 224 / 129 / 144 | `1110 0000` / `1000 0001` / `1001 0000` | briefly at night | turning over / awakening |

**Criterion: `kind & 0xF0 == 0xF0`, i.e. the top four bits are all 1, is the band's sleep family**
(240/249/250 hit it; it never hit once during the day). But within that family `0xF3` is the
exception — Gadgetbridge applies `rawKind & 0x0f` to the same byte, where a low nibble of `3` is
`TYPE_NONWEAR`; real-device data independently supports this (see §6.2).

## 4. So how is sleep staging done

Derive from three reliable signals instead of guessing at fields:

- **Sleep window**: continuous runs of `kind & 0xF0 == 0xF0`, tolerating a few still minutes in
  between;
- **Awakening**: within a run, `steps > 0` or `intensity ≥ 20`;
- **Deep sleep / REM**: use the heart-rate distribution quantiles over the whole sleep run (deep
  sleep = low quantile with no body movement, REM = high quantile with no body movement), and
  smooth them with a minimum duration.

The implementation is in [`miband_monitor/sleep/`](../../miband_monitor/sleep/); derivation results
are always marked `derived: true` and kept strictly distinct from the band's raw fields.

> This derivation is **heuristic**: the wrist has only heart rate and body movement, no EEG, so the
> accuracy ceiling for true staging lies right there. Its value is in trends and structure (sleep
> onset/wake times, total duration, deep-sleep ratio, number of night awakenings), not per-minute
> medical interpretation.

## 5. What these three bytes actually are: per-minute stage scores

The previous section only proved "not a duration". Comparing the 01-06 night (365 sleep minutes,
with heart rate) against the 01-07 night (680 minutes, **not a single heart-rate reading all
night**) can rule out three further hypotheses and pin down one reading.

### 5.1 Excluded: not a counter, not packed bits, not a probability split

| Hypothesis | Counter-evidence |
| --- | --- |
| Cumulative minutes | The per-minute difference averages 0 (+0.00 / -0.03 / -0.12) and never accumulates monotonically; `deep` can jump from 28 to 57 between two adjacent minutes |
| 2-bit / 4-bit packing | The high-bit pattern is constant, 1073 and 1074 fall in the same "group", and no packing split matches |
| The three are a probability split of the same minute | `corr(light, deep+REM) = **+0.20**`, while complementarity would require ≈ -1; more fatally, on the night without heart rate only `light=61` and `deep=REM=0`, so read as a split that would declare 52% of that night awake — yet the person slept all night |
| A "total sleep score" unrelated to movement | On the night without heart rate, `light` stays at `61 ± 1` for 11 hours straight, and only it responds to movement |

### 5.2 Behavior of each of the three columns

| Column | Night without heart rate | Night with heart rate (365 minutes) | vs heart rate | vs body movement |
| --- | --- | --- | --- | --- |
| `sleep` (light sleep) | `61.2 ± 1.0`, unchanged all night | mean 54.5, median 57, range 17–62 | unrelated (r = -0.04) | **strongly correlated**: walked for 24 minutes at 22:22, the value went 58 → 17 → 13, then climbed back to 52 over the next 5 minutes |
| `deep_sleep` (deep sleep) | all 0 | mean 35.0, range 13–54 | **negative correlation** r = -0.34 | unrelated |
| `rem_sleep` (REM) | all 0 | mean 28.5, range 13–78 | **positive correlation** r = +0.23 | unrelated |

Binned, it becomes clearer (night 1):

| Heart rate in that minute | Deep-sleep mean | REM mean |
| --- | --- | --- |
| 45–49 | 38.3 | 27.1 |
| 50–54 | 34.6 | 26.8 |
| 55–59 | 29.8 | 34.8 |
| 60–64 | 26.9 | 35.1 |
| 65–69 | 19.6 | 49.8 |

Deep sleep and REM are **inversely monotonic** with `r = -0.43` between them: this is the output
of a pair of competing discriminants, unlike two independent measurements. Conclusion:
**`deep_sleep`/`rem_sleep` are stage-discrimination scores computed by the band from that minute's
heart rate; without heart rate they cannot be computed; `sleep` is a light-sleep score computed
from body movement alone.**

### 5.3 The candidate reading at the time: `score / 128` = proportion of that minute attributed to this stage

> **This section was overturned by §7.** At the time there was only internal-consistency evidence
> (the three categories summed to 329 minutes, roughly equal to the 328 minutes of sleep judged by
> body movement), and it looked self-consistent. After obtaining Zepp Life's measured numbers: the
> app reported 44 minutes of deep sleep, while this section integrated 96 minutes. That Zepp page
> also had no REM row, but the reason is not that it does not support REM (§8 overturns that
> judgment), but that REM was 0 that night. Numerical self-consistency does not equal semantic
> correctness; this section is kept as a record of the process.

All three bytes fall in 0–127 (bit7 of `deep`/`rem` is a "scored" flag); treating `value/128` as
the stage proportion of that minute and integrating gives expected minutes (night 1, 357-minute
window):

| Stage | Integrated minutes | Proportion |
| --- | --- | --- |
| Light sleep | 151 | 42% |
| Deep sleep | 96 | 27% |
| REM | 82 | 23% |
| Unattributed | 28 | 8% |

- The three categories sum to 329 minutes, 1 minute away from "328 minutes asleep as judged by body
  movement";
- Unattributed is 28 minutes, 1 minute away from "29 minutes awake as judged by body movement";
- Deep sleep 27% / REM 23% falls inside physiological priors (wristwatch algorithms generally
  report 20–30%).

For the same night, the heuristic of §4 (heart-rate quantile + HRV quantile) gives 40 minutes of
deep sleep (12%) and 55 minutes of REM (17%) — deep sleep is clearly too low. The two results differ
in the deep-sleep/REM split, which is exactly where Zepp's measured numbers are needed to
adjudicate.

### 5.4 Interfacing with Zepp: one reading settles it

Zepp's **time** is the integrated result of these three columns, while the **score** is an additional
weighted score the app computes on top of time (duration, efficiency, ratios); it is impossible to
invert uniquely from the three columns. So only verify **time**:

| If Zepp shows for that night | Then it means |
| --- | --- |
| Deep sleep ≈ 1 h 36 min, REM ≈ 1 h 22 min, light sleep ≈ 2 h 31 min | the 1/128 integration reading of 5.3 holds and can directly replace the heuristic |
| Deep sleep ≈ 40 min, REM ≈ 55 min | the heuristic's quantile split is closer to Zepp; use the three columns only as trends |
| None of the above | the three columns are some other quantity (e.g. band-side cached staging results); another mapping must be found |

`python -m sleep_analysis --db mi_band.db` prints both sets of numbers side by side (the
`band scores` line); the sleep derivation section of `docs/guides/usage.md` has the full parameters.

## 6. Cross-check against the Gadgetbridge source (2020-01-08, master `db00876`)

This section is **external evidence**, not inference: Gadgetbridge uses the same Huami protocol and
its code can be consulted directly. The cross-check yields four conclusions, two of which
overturn/correct statements made earlier in this document.

### 6.1 The 8-byte layout matches field by field

`createExtendedSample()` in
`service/devices/huami/operations/fetch/FetchActivityOperation.java:152` reads 8 bytes in order,
with naming identical to this project:

```java
huamiExtendedActivitySample.setRawKind(value[i] & 0xff);
huamiExtendedActivitySample.setRawIntensity(value[i + 1] & 0xff);
huamiExtendedActivitySample.setSteps(value[i + 2] & 0xff);
huamiExtendedActivitySample.setHeartRate(value[i + 3] & 0xff);
huamiExtendedActivitySample.setUnknown1(value[i + 4] & 0xff);
huamiExtendedActivitySample.setSleep(value[i + 5] & 0xff);
huamiExtendedActivitySample.setDeepSleep(value[i + 6] & 0xff);
huamiExtendedActivitySample.setRemSleep(value[i + 7] & 0xff);
```

And the Mi Band 6 does take this path: `MiBand6Support.getActivitySampleSize()` returns `8`.
**This project's naming and position for `unknown1` are therefore confirmed as well.**

### 6.2 The low nibble of `kind` is the activity code; `3` = not worn

`MiBand2SampleProvider.postprocess()` does `rawKind &= 0xf` for each minute, then maps through
`HuamiConst`: `1` activity, `3` **not worn**, `9` light sleep, `10` ignore, `11` deep sleep,
`12` wake, `0` no change. The comment in the same file points exactly at the high-frequency
values in our data:

```java
// all I ever had that are 0 when doing &=0xf
RawKind.notIn(TYPE_NO_CHANGE, TYPE_IGNORE, TYPE_UNSET, 16, 80, 96, 112)
```

`16 / 80 / 96 / 112` are exactly the high-frequency kinds among this project's 1920 minutes — two
independent paths agree on the same set of bytes.

**This corrects the criterion in §3 of this document.** Previously `kind & 0xF0 == 0xF0` was
uniformly treated as sleep, whereas the low nibble of `243 (0xF3)` is `3`. Real-device data
independently supports the "not worn" reading:

| kind | Minutes | Has valid heart rate | Zero intensity and zero steps |
| --- | --- | --- | --- |
| 240 (0xF0) | 330 | **329 (99.7%)** | 266 |
| 249 (0xF9) | 9 | 9 (100%) | 3 |
| 250 (0xFA) | 27 | 27 (100%) | 27 |
| **243 (0xF3)** | **679** | **0 (0.0%)** | **679** |
| 115 (0x73) | 18 | 0 (0.0%) | 18 |

PPG needs skin contact: with the band off the wrist not a single heart-rate reading can be
measured, and it does not move when left on a table either. The 679 minutes simultaneously satisfy
"zero heart rate + zero displacement", while almost every other kind has heart rate about 100% of
the time — so the night of 01-07 20:08 → 01-08 07:40 was not "11.3 hours in bed" but **the band was
not worn**. `sleep_analysis.py` and the dashboard were changed accordingly to "not worn" and no
longer generate a sleep segment for that night.

This criterion was later **independently confirmed by wear status**, which is independent of PPG's
physical constraint: one is a necessity on the data side (no measurable pulse means no skin
contact), the other is an independent wear-status check. Both agree, so `0xF3` = not worn can be
taken as settled.

### 6.3 Gadgetbridge did not solve these three bytes either; it only gave thresholds

The comment and code of `devices/huami/HuamiExtendedSampleProvider.java:124`:

```java
// Fallback to the old threshold-based approach, which is not accurate
// Band reports type sleep regardless of sleep type, so we map it to custom raw types
// These thresholds are arbitrary, but seem to somewhat match the data that's displayed on the band
sample.setDeepSleep(sample.getDeepSleep() & 127);
sample.setRemSleep(sample.getRemSleep() & 127);
if (sample.getRemSleep() > 55) { ... REM ... }
else if (sample.getDeepSleep() > 42) { ... deep ... }
```

Three points worth noting:

1. It likewise treats bit7 as a flag (`& 127`), consistent with §5's judgment;
2. It likewise does **not** treat these three bytes as durations, but as **per-minute scores**
   compared against thresholds — the same family as the 5.3 reading, only "threshold counting"
   rather than "1/128 integration";
3. The author explicitly writes that these thresholds are **arbitrary** and that the method is
   **not accurate**.

Applying this threshold scheme to this project's 01-06 night (365 sleep minutes) gives: light sleep
203, deep sleep 128 (35%), REM 34 (9.3%). Deep sleep 35% / REM 9% deviates from physiological common
sense (REM has 4–5 cycles per night and cannot be only 9%), whereas 1/128 integration gives deep
sleep 27% / REM 22%. **Conclusion: Gadgetbridge's 42/55 constants were fitted from other models and
cannot be taken as the answer for the Mi Band 6.**

### 6.4 The real staging on the band side goes through another command, which the Mi Band 6 does not have

Gadgetbridge's preferred path fetches `SLEEP_SESSION` (fetch type `0x48`); each record is 594 bytes
(`HuamiSleepSessionSampleProvider.SleepSession`):

| Offset | Type | Meaning |
| --- | --- | --- |
| `0x000` | u32 | Session timestamp |
| `0x004` | u32 | Midnight of that day (local time zone) |
| `0x00a` / `0x00c` | u16 | Sleep start / end (minutes since noon of the previous day) |
| `0x015` | u8 | Average heart rate |
| `0x016` | u8 | **Sleep score** |
| `0x054` | u8 | Number of stage segments (≤100) |
| `0x056` | 5×n | Per segment `u16 start, u16 end, u8 type`; type `4` light / `5` deep / `7` awake / `8` REM |
| `0x24a`–`0x250` | u16×4 | REM / light / deep / awake total minutes |

The structure is self-consistent: `0x56 + 5×100 = 0x24a`; the 100 staging slots exactly fill up to the
summary fields, and 594 lands exactly at the end. This is where Zepp's "sleep time / deep sleep time
/ light sleep time + score" comes from.

But **Gadgetbridge does not send this command to the band 6**: `HuamiFetcher.java:101` requires
`coordinator.supportsSleepScore(device)`, while that method's default implementation returns
`false` and `MiBand6Coordinator` does not override it (only ZeppOS models such as Band 7, Bip 5 and
GTR3 override it to `true`).

**Real-device verification** (`tools/probe_fetch_types.py`, 2020-01-08):

```
type 0x48: reply 10010100000000b207010100000000   accepted, declares 0
type 0x2c: reply 10010100000000b207010100000000   accepted, declares 0
type 0x01: reply 100101db070000ea070b0117070020   accepted, declares 2011
```

`0x48` and `0x2c` both have status `0x01` (success) but declare 0 records and return a 1970-01-01
calendar — the protocol layer recognizes this type, but the firmware has no data. By contrast
`0x01` declares 2011 minutes and returns a real calendar. **The Mi Band 6 firmware does not produce
sleep session records at all**, which matches Gadgetbridge's behavior of not requesting them from
it.

### 6.5 Gadgetbridge is itself using "derivation"

For devices that cannot obtain session records, Gadgetbridge's latest approach is
`util/sleep/SleepStageEstimator.kt` (added recently): wake/sleep uses Cole-Kripke weights plus
Webster rescoring; staging uses the deviation of heart rate from a **rolling baseline**, heart-rate
variability, time priors (deep sleep biased toward the first half of the night, REM toward the
second half) plus a movement penalty, and finally a closed loop with "deep sleep share 10–25%, REM
15–30%" that adapts the thresholds into that range.

It **does not read those three bytes at all**; the file header itself says *"This is a heuristic
without ground truth. Read the stages as 'when heart rate was low and steady versus high and
variable', not as a sleep lab."*

It belongs to the same family as this project's current heuristic (heart-rate quantile + HRV
quantile), but its engineering is more complete. Two things are worth borrowing: ① use **rolling
baseline deviation** instead of global ranking, which keeps up with "heart rate continuously
declining through the night"; ② adapt thresholds with a proportion closed loop instead of fixed
quantiles — the latter is exactly why this project's deep sleep is only 12% (too low).

### 6.6 What this means for this project

`0x48` being empty shows that **there are no staging results in the Mi Band 6 firmware**. So where
does the "deep sleep 1 h 36 min" screen shown on Zepp come from? It can only have been **computed**
by the app/cloud from the same activity samples (`kind` + those three bytes + heart rate) — the same
as what Gadgetbridge does for such devices, and the same as what this project does.

So the adjudication method of §5.4 still holds, and is now even clearer: **the deep-sleep/REM
durations for that night on Zepp are the only external evidence that can separate the "1/128
integration" and "threshold counting" readings**, because both sides consume the same set of raw
bytes.

| If Zepp shows for the 01-06 night | Meaning |
| --- | --- |
| Deep sleep ≈ 1 h 36 min (96), REM ≈ 1 h 22 min (82), light sleep ≈ 2 h 31 min (151) | the 1/128 integration reading agrees with Zepp and can replace the heuristic |
| Deep sleep ≈ 2 h 08 min (128), REM ≈ 34 min | Gadgetbridge's 42/55 threshold reading agrees with Zepp |
| Deep sleep ≈ 40 min, REM ≈ 55 min | this project's current heuristic is closer to Zepp; use the three bytes only as trends |
| None of the above | the three bytes are unrelated to Zepp's staging; Zepp used other signals (e.g. the raw acceleration series) |

## 7. Zepp Life's measured numbers: the three bytes are not stage durations (2020-01-08)

The Zepp Life sleep page used for comparison adjudicated all the earlier hypotheses at once. The
original page text: **sleep score 73** (better than 34% of users), **8 h 40 min**, **deep sleep 44
minutes (8%)**, **light sleep 7 h 56 min (92%)**, **awake 20 minutes**, naps 0 minutes, timeline
21:06 → 06:06.

Note that this page **has no REM row**. At the time I wrote "this model does not support REM" based
on it, **and that conclusion was overturned in §8**: Zepp does have a REM category (the 01-07 page
shows 1 h 27 min / 23%); the row is missing on this page because the UI does not show it when REM is
0. 8h40m + 20min = 9h00m exactly equals 21:06 → 06:06; these numbers are self-consistent.

### 7.1 Comparison of the three readings

For the night of 01-06, the part we synced is 22:06 → 06:06 (481 minutes); the hour 21:06-22:06 is
not in the database. Scaled on that basis, Zepp should show about 460 minutes of sleep and 44
minutes of deep sleep in the overlapping interval (deep sleep in that hour is unknown, so 44 is an
upper bound).

| Reading | Deep sleep | Proportions of both | Conclusion |
| --- | --- | --- | --- |
| `score/128` integration | 96 minutes | deep 27% / REM 23% | **No**: deep sleep is off by 52 minutes, and it counts REM as 82 minutes (the app reported 0 that night) |
| Gadgetbridge thresholds (REM>55 / deep>42) | 128 minutes | deep 35% / REM 9.3% | **No**: deep sleep is off by 84 minutes |
| This project's heuristic (old window) | 40 minutes | deep 12% | numerically closest, but the window is only 5.5 hours |

**The three bytes are not stage durations; this point is now settled.** But the reason is not
"Zepp has no REM" — it does (§8). The real reason is in §8.3: `rem_sleep` is non-zero for 458/485
minutes on the 01-06 night (the app reported **0** REM minutes), yet is all `0x80` on the 01-07 night
(the app reported **87** REM minutes). The direction is reversed.

### 7.2 What Zepp actually uses is body movement + heart rate

Reverse-engineering the same data stream, Zepp's three rules can be reproduced exactly:

| Quantity | Zepp | Our data | Difference |
| --- | --- | --- | --- |
| Awake | 20 minutes | minutes with `steps > 0`: **17** | 3 |
| Sleep | 520 minutes | 481 − 17 = **464** (overlap interval) | the overlap interval should be 460 |
| In bed | 540 minutes (21:06→06:06) | 22:06→06:06 = **480** | 0 |

By comparison, judging awake with `intensity >= 20` gives 72 minutes (55 minutes of real sleep
undercounted), and judging the sleep window with `kind & 0xF0 == 0xF0` gets only 357 minutes (124
minutes lost at both ends in total). So: **awake = has steps; sleep window = band-reported sleep as
the anchor + still extension on both sides**; that is the current implementation.

The output for the same 01-06 data after the fix:

| Metric | Ours | Zepp (scaled to the overlap interval) |
| --- | --- | --- |
| In bed | 22:06 → 05:55, 470 minutes | 22:06 → 06:06, 480 minutes |
| Sleep | 453 minutes | ~460 minutes |
| Awake | 17 minutes | 20 minutes |
| Deep sleep | 50 minutes (11%) | 44 minutes (8%) |

Deep sleep is still 6 minutes too much. The decision thresholds (`DEEP_HR_RANK=0.20`,
`DEEP_SD_RANK=0.45`) were tuned on this night, **only one night of samples, so they are
provisional values**, to be converged once there are more Zepp nights.

### 7.3 Lessons

Several previous rounds kept looking for the answer in "which byte corresponds to which stage". The
real answer is: **this model has no readable stage durations**; the app also computes them on the fly
from body movement and heart rate. The three bytes are scores, `kind` is the state machine, and
neither is a staging table; forcing either of them to be interpreted as a staging table yields
numbers that do not match the app.

The second lesson is more worth recording: **do not judge a device's capabilities from one UI page**.
The 01-06 page lacked the REM row, and I concluded from it that "Zepp Life does not show REM for
this band"; that conclusion was overturned the same day by a third page — a missing row only means
REM was 0 that night. Likewise, when the numbers on one page do not match, it may also mean that
page was not produced by this device at all (§8.2).

## 8. Two more pages of Zepp data: REM does exist, but neither night is usable (2020-01-08 15:55)

The two pages added afterwards. They **simultaneously** overturned a claim in the previous section
and provided a stronger piece of counter-evidence, but neither could be used to calibrate the three
bytes.

### 8.1 Original numbers from the three pages

| Date | Sleep score | In-bed window | Sleep | Deep sleep | Light sleep | REM | Awake | Naps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01-05 | 75 (better than 38%) | 21:16 → 05:42 (8h26) | 8h05 (485) | 44 (9%) | 7h21 (441, 91%) | **no such row** | 21 | 20 |
| 01-06 | 73 (better than 34%) | 21:06 → 06:06 (9h00) | 8h40 (520) | 44 (8%) | 7h56 (476, 92%) | **no such row** | 20 | 0 |
| 01-07 | 92 (better than 90%) | 22:44 → 05:11 (6h27) | 6h27 (387) | 1h14 (74, 19%) | 3h46 (226, 58%) | **1h27 (87, 23%)** | 0 | 0 |

All three rows are self-consistent: sleep + awake = in bed (485+21=506, 520+20=540, 387+0=387).

**On seeing this page I withdrew the judgment that "this band does not show REM" — and that
withdrawal went too far.** After six nights were added the next day (§8.6) it is visible that all
five nights when the band was worn have no REM row, and the only night with REM happens to be a
night when the band was not worn. So the observation in the previous section (this band's nights
have no REM) actually holds; my mistake was treating another device's page as this device's
capability. The same lesson was learned twice in one night; it is written into §7.3.

### 8.2 But on the night of 01-07, the band was not on the wrist at all

Zepp's 01-07 window (22:44 → 05:11) falls inside our activity history, and fetching it looks like
this:

| Item | Value |
| --- | --- |
| Minutes | 396 (22:44 → 05:11, not a single minute missing) |
| `kind` | **396/396 all `0xF3` (243, not worn)** |
| Heart rate | **0/396** |
| Steps / intensity | all 0 |
| Raw values of `deep_sleep` / `rem_sleep` | **396/396 all `0x80`** ("scored, value 0") |

Widening to the whole not-worn interval (01-07 20:22 → 01-08 07:40, 679 minutes), there is likewise
not a single heart-rate reading. PPG needs skin contact (§6.2), so the band was not on the wrist
that night; a band that is not on the wrist cannot know "deep sleep 74 minutes, REM 87 minutes".

**Conclusion: the 01-07 page was not produced by this band.** The fact that the band was not worn
all night has been independently confirmed (see the end of §6.2), so that page can only be data from
another device under the same Zepp account — which one the diary page shows depends on which record
Zepp selected that day.

The 01-05 page does not even have the precondition for comparison: this project's activity history
starts only at 01-06 22:06 (the request was issued for 7 days, and the band returned only 2011
minutes); that night was never synced.

### 8.3 Inversion: the switch for the three bytes is "sleep window + heart rate", not stage

Putting the two nights side by side, the conclusion is firmer than in the previous section:

| Night | REM reported by the app | Low 7 bits of `rem_sleep` | Deep sleep reported by the app | Low 7 bits of `deep_sleep` | Heart-rate coverage |
| --- | --- | --- | --- | --- | --- |
| 01-06 | **0 minutes** | **458/485 minutes non-zero** | 44 minutes | 458/485 minutes non-zero | 485/485 |
| 01-07 | **87 minutes** | **396/396 all 0** | 74 minutes | 396/396 all 0 | 0/396 |

When the app reports 0 the bytes are non-zero in almost every minute, and when the app reports 87
minutes the bytes are all zero. **The direction is reversed**, which is even more decisive than "the
numbers do not match": no monotonic scaling can make both columns hold at the same time.

Look at the switch condition again. Whole database, 1920 minutes:

- The **463 minutes** where the low 7 bits of `rem_sleep` are non-zero **all** have heart rate in
  that minute;
- The 755 minutes with heart rate but 0 bytes all fall in daytime non-sleep segments (`kind` is
  80/96/1/16 etc.).

So the semantics of these two columns are: **"a discriminant score computed by the band while it is
in the sleep window and there is heart rate in that minute"**. It has no correspondence with the
stage minutes shown by the app, and the direction is even reversed. The observation in §5 that
"deep sleep negatively correlates with heart rate, REM positively correlates with heart rate" is
true — it is just that the discriminant is not the staging that Zepp displays.

### 8.4 Only one night is usable now; how should samples be added

| Night | Status | Usable for calibration |
| --- | --- | --- |
| 01-05 | not in the database (lost before sync) | no |
| 01-06 | usable, but missing the hour 21:06–22:06 | **yes (the only night)** |
| 01-07 | not worn (679 minutes of 0xF3) | no, but it is a **negative control** — proving the bytes ≠ stages |

One night can be aligned with any reading; tuning parameters at this sample size is just
reverse-engineering magic values from the data. Therefore
[`tools/calibrate_sleep.py`](../../tools/calibrate_sleep.py) was added: it puts four readings
(1/128 integration, Gadgetbridge thresholds, this project's heuristic, per-threshold sweep) in the
same table, and **refuses to give a fitting conclusion when usable nights < 2**, listing only the
differences:

```
$ ./.venv/Scripts/python.exe tools/calibrate_sleep.py
2020-01-05  44/441/0/21    —                    库里没有这一夜（同步前就被手环清掉了）
2020-01-06  44/476/0/20    01-06 22:06→05:55    可用（470 分钟，470 条心率）
2020-01-07  74/226/87/0    —                    手环那一夜未佩戴（693 分钟 0xF3，无心率）

2020-01-06  integral    120 / z44   106 / z0   173 / z476
2020-01-06  gb          136 / z44    58 / z0   276 / z476
2020-01-06  heuristic    50 / z44     0 / z0   403 / z476

结论：只有 1 个可用夜晚。**不做拟合**……
```

To add samples, three steps per night: **sleep with it on → sync that day → record that day's Zepp
numbers into `data/zepp_nights.json`**. The second step is a hard prerequisite: after receiving the
`03` ack the band clears the uploaded minutes; that is how 01-05 was lost. Record format:

```json
{"date": "2020-01-06", "score": 73, "window": ["21:06", "06:06"],
 "asleep_min": 520, "deep_min": 44, "light_min": 476, "rem_min": 0, "awake_min": 20}
```

After accumulating 3–5 nights, the tool will give two conclusions: which reading has the smallest
deep-sleep/REM error, and **whether the fixed thresholds are consistent across nights** (consistency
would show the three bytes can really be used as stages; inconsistency means they can only be used
as trends).

### 8.5 Two confirmations: one already answered, one became a more pressing question

**Second question (whether the band was not worn that night of 01-07): confirmed not worn.** Wear
status was independently checked and is consistent with the PPG criterion in §6.2. `0xF3` = not
worn is settled by this.

**First question (whether multiple devices are bound): instead became more critical.** Since the
band was not on the wrist that night yet Zepp gave complete staging, that shows **the app's sleep
page is not always this band's data**. This has two direct consequences:

1. **The premise "Zepp numbers = this band's baseline" must be verified night by night.** Calibrating
   with nights of the wrong source is worse than not calibrating — it would import another device's
   algorithm conclusions into this project's staging model. `tools/calibrate_sleep.py` therefore
   adds two gates: nights when the band was not worn are directly marked "this page comes from
   another device" and excluded, and nights with an empty `device` field are flagged with the
   warning "source device not recorded".
2. ~~The night of 01-06 is also worth doubting~~ — **this doubt has been ruled out by six nights of
   data.** Deep-sleep minutes across six nights are 62 / 58 / 68 / 44 / 44 / 74, i.e. 8%–19% of
   sleep, neither a constant nor a fixed ratio. The two 44s are a coincidence, not "cut at ~8.5%"
   (§8.6).

So the next step is not to compare numbers again, but to **determine the source first**: open Zepp
Life's sleep details page (or "My Devices") and see which device that night's record is under. Only
when the source is confirmed to be Mi Band 6 does a night qualify for the `device` field of
`data/zepp_nights.json`, and only then can calibrating the three bytes be discussed.

### 8.6 Six nights side by side (01-01 / 01-02 / 01-03 added at 16:14)

The user added three more pages, and the complete numbers for six nights are as follows (each row is
self-consistent: deep + light + REM = sleep, sleep + awake = in bed):

| Date | Score | In bed | Sleep | Deep sleep | Light sleep | REM | Awake | Did the band have that night |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01-01 | 75 (better than 38%) | 23:06 → 07:36 (8h30) | 7h57 (477) | 1h02 (62, 13%) | 6h55 (415, 87%) | — | 33 | no |
| 01-02 | 86 (better than 71%) | 22:07 → 06:35 (8h28) | 8h27 (507) | 58 (11%) | 7h29 (449, 89%) | — | 1 | no |
| 01-03 | 88 (better than 78%) | 21:45 → 06:34 (8h49) | 8h40 (520) | 1h08 (68, 13%) | 7h32 (452, 87%) | — | 9 | no |
| 01-05 | 75 (better than 38%) | 21:16 → 05:42 (8h26) | 8h05 (485) | 44 (9%) | 7h21 (441, 91%) | — | 21 | no |
| 01-06 | 73 (better than 34%) | 21:06 → 06:06 (9h00) | 8h40 (520) | 44 (8%) | 7h56 (476, 92%) | — | 20 | **yes** (missing 21:06–22:06) |
| 01-07 | 92 (better than 90%) | 22:44 → 05:11 (6h27) | 6h27 (387) | 1h14 (74, 19%) | 3h46 (226, 58%) | **1h27 (87, 23%)** | 0 | no (not worn) |

This table settles three things and nails one lesson down once and for all.

**① REM appears only on the night that was "not the band".** All five nights when the band was worn
have no REM row. So the observation in §7 (this band's nights have no REM) is itself correct, and my
withdrawal in §8.1 was what was wrong. The same lesson was learned twice in one night:

- §7: one page had no REM → asserted "this device does not support REM" (treating one page as
  capability);
- §8.1: another page had REM → asserted "what I said before was wrong" (treating **another
  device's** page as this device's capability).

The correct statement is: **the n=5 observation — this band's nights have no REM**; REM appears in
another device's nights. The inversion in §8.3 is therefore fully explained: the `rem_sleep` byte
is not REM duration, and the app does not give this band a REM row at all.

**② The doubt that "44 minutes is a fixed ratio" is ruled out.** Deep sleep across six nights is
**62 / 58 / 68 / 44 / 44 / 74** minutes, i.e. **8%–19%** of sleep, neither a constant nor a fixed
percentage. The two 44s are a coincidence; my earlier hypothesis of "cut at ~8.5%" does not hold.

**③ The score mainly penalizes awakenings, not rewards duration.** Sorted by awake minutes:

| Date | 01-07 | 01-02 | 01-03 | 01-06 | 01-05 | 01-01 |
| --- | --- | --- | --- | --- | --- | --- |
| Awake (minutes) | 0 | 1 | 9 | 20 | 21 | 33 |
| Score | 92 | 86 | 88 | 73 | 75 | 75 |

Correlation coefficients: score vs awake **-0.87**, vs sleep efficiency **+0.86**, vs deep-sleep
ratio +0.78, vs sleep duration **-0.47** (negative — the night with the highest score slept only
6h27m). The three nights with awake ≤9 minutes are 86/88/92, and the three with ≥20 minutes are
73/75/75; the two groups are completely separated.

This is useful for the project: the `efficiency` and `awakenings` reported by this project are the
same family of signals as Zepp's score (01-06: ours 17 minutes awake, efficiency 96%; Zepp 20
minutes, score 73). But it also reminds us of one thing — **the score cannot be used as a
verification baseline**; its weight on awakenings is far greater than on deep sleep, and what we can
reliably measure is exactly sleep duration and awakenings.

**④ A usable prior is obtained along the way.** Across five band nights, deep sleep is 8%–13% of
sleep (median 11%). This project reports 11% for 01-06 (50 / 453), which falls inside that range.
**So there is no need to twist thresholds just to make some number match** — this is exactly the
mistake most easily made in the previous rounds.

Six nights bought only one prior, not a second calibration night: 01-01/02/03/05 are all earlier
than the start of the band's activity history (01-06 22:06). That is the only thing to solve in the
next round — **sync once every morning, and nights will accumulate**.

## 9. Why Zepp has it and the band does not: a three-layer chain

This question appeared three times (the minute data of 01-01/02/03/05, staging such as deep
sleep/REM, and the whole night of 01-07), but **the reasons are completely different each time**.
They can be confused because "the data on Zepp" actually comes from three different layers:

```
Band (minute-level ring buffer)
   ↓  BLE fetch (0x01 / 0x25 …)
Zepp on the phone (local database, also uploaded to the cloud)
   ↓
Cloud (computes staging, computes the score, merges multiple devices under the same account)
```

**This project talks only to the first layer.** The app sees the second and third layers, so "Zepp
has it" never equals "the band has it and we failed to fetch it".

### 9.1 Three situations, distinguished at a glance

| Situation | Example | Where the thing originally was | Can we get it |
| --- | --- | --- | --- |
| ① The band has it, but the app already took it | the minute data of 01-01/02/03/05 | phone local database + cloud | **No** — it is gone if not synced that day |
| ② The band never computed it | deep sleep / light sleep / REM / sleep score / sleep breathing quality | never existed on the band | no, and no need: the raw data is in our hands |
| ③ The band was not worn | 01-07 | another device under the same account | no (it was not its data to begin with) |

### 9.2 ① The band is only a buffer; the app reclaims it after fetching

The last step of the protocol is `0x03`, called `COMMAND_ACK_ACTIVITY_DATA` in Gadgetbridge — the
equivalent of an "I received it" receipt; whether it is reclaimed afterwards is decided by the
firmware (the source is not visible for this step, but the behavior matches).

Measured: when requesting 7 days, the band's minute data **only goes back to within the last 40
hours** (the 01-08 14:05 fetch was 01-06 22:06; the 01-08 16:25 fetch was 01-07 00:25), while on the
app records from 01-01 onward are all present. The window size and shift rate are quantified in
§10.

> An easy pitfall along the way: **do not subtract "stored rows" from "declared count"**. The number
> in the reply (e.g. 2011) is the count **declared by this fetch**, while the database holds
> **de-duplicated** rows (1920). The two measures differ; a difference of 91 does not imply "91
> minutes were missed". To judge whether anything was missed, only look at whether the time range is
> covered continuously.

### 9.3 ② The band does not produce staging; the app computes it on the fly

What the band uploads is `kind` / `intensity` / `steps` / `heart_rate` plus three scores, **not**
things like "deep sleep 44 minutes". The evidence is §6.4: `0x48 SLEEP_SESSION` declares 0 records on
this firmware — if the band computed and stored staging itself, it would have to exist somewhere
readable.

So Zepp's screen of deep/light sleep is computed on the fly by the app (or cloud) after receiving
the same batch of raw data. This has two implications:

- It is not "we failed to fetch it", but "it never existed in minute form";
- But it **proves this is feasible**: with the same batch of `kind` + heart rate, the app can compute
  staging, and so can we — the difference is only the algorithm, not the data channel. This is also
  the footing of this project's `sleep_analysis.py`.

### 9.4 ③ Data in the account is not necessarily this device's

01-07: the band's 679 minutes are all `0xF3` (not worn), 0 heart-rate readings, yet the app has
complete staging of 6h27 (§8.2). So "Zepp has it" cannot even guarantee "some device recorded it" —
it may come from another device under the same account.

### 9.5 Decision order (three steps are enough)

1. Is `kind` equal to `0xF3` (not worn)? → situation ③;
2. Is the timestamp earlier than the band's current range (only the last 40 hours are kept, see
   §10)? → situation ①;
3. Is the time within range and the data present, but the fields app-only (staging/score/breathing
   quality)? → situation ②.

After this comparison, only ① is "regrettable but salvageable": **sync once that day and the night
is kept**. ② and ③ will never appear no matter how many times you sync, because they were never in
the band to begin with.

---

## 10. How long does the band actually keep data: measurement of the 40-hour window (2020-01-08 16:25)

§9 said "the band is only a buffer", but at the time that was only a qualitative description. This
section quantifies it: fetch once more, probe the "declared window" once, then compare the
overlapping part of the two fetches byte by byte.

TL;DR: **the band's minute data is a sliding window of 2400 minutes (exactly 40 hours); the front end
is evicted at a rate of one row per minute, and the segments the app has taken leave permanent
holes. `--sync-history 7` will never give you 7 days.**

### 10.1 Two fetches: the window shifted forward as a block by 139 minutes

| Fetch time | Data range (local time) | Rows | Span |
| --- | --- | --- | --- |
| 01-08 14:05 | 01-06 22:06 → 01-08 14:05 | 1920 | **2399 minutes** |
| 01-08 16:25 | 01-07 00:25 → 01-08 16:24 | 1920 | **2399 minutes** |

The two fetches are 140 minutes apart, and the start moved forward by exactly 139 minutes — **1:1**.
That is, for every minute of new data written, one minute of the oldest data is pushed out; it is
not "deleted on expiry" but "overwritten".

The span is exactly 2399 minutes both times (2400 minute slots); this is no coincidence: **window
width = 2400 minutes = 40 hours.**

Direct consequence: the night of 01-06 is outside the 16:25 window, and from this moment on **no
matter how many more times you sync, it cannot be recovered**. To keep a night, there is only one
path — sync once within 40 hours after that night ends (once a day is safer).

### 10.2 1920 rows vs 2400 minutes: the 481-minute hole in between

Both fetches have the same hole: **01-07 07:22 → 01-07 15:23, 481 minutes**. 2400 − 481 = 1919, plus
one endpoint back gives 1920.

The key is that "the hole's position did not move between the two fetches". If it were "a blank left
by the sliding window", it would move together with the window; it did not move, which means **these
rows were deleted**, not that they were never recorded — that is exactly the segment the phone
automatically synced, took and acknowledged while it was carried during the day (8 hours, exactly
one working day).

So:

- `1920` is **not** the band's capacity limit, but "40-hour window − the 8 hours already bitten off
  by the app";
- The earlier 91-minute difference between "declared 2011 / stored 1920" is the same kind of
  measurement issue, not missed fetching;
- Conversely, if the app has not synced for a while, you can get close to 2400 rows in one go.

### 10.3 An ask-only probe: `tools/probe_declared.py`

To confirm "how big the window is", you cannot rely on fetching — each fetch sends a receipt and
changes the band's state. So a probe was added: it only sends `01 01 <6B time><reason><tz>` (asking
"how much do you have left from this moment"), **fetches no data and sends no `0x03`**, and
disconnects after asking.

```
$ .venv/Scripts/python.exe tools/probe_declared.py 168 24
                 since   declared            first sample  note
2020-01-01T16:32+08:00       2406        2020-01-01T16:32  since+2406min -> 2020-01-03T08:38+08:00
2020-01-07T16:32+08:00       1437        2020-01-07T16:32  since+1437min -> 2020-01-08T16:29+08:00
```

Each of the two lines of readings explains one thing:

- Ask **7 days ago**, the band answers **2406 minutes** (40.1 hours), not 7×1440=10080. It trims the
  question to its own window when answering, **asking earlier is useless**;
- Ask **24 hours ago**, the band answers **1437**, roughly equal to "until now" — the whole day is
  within the window, not a single minute missing.

(The `first sample` column: the band echoes the request time verbatim; it does not represent the
real start of the corpus, so do not use it as an anchor. The count itself also has a quantization
error of a few minutes: the 16:27 reading was 2411, the 16:32 reading was 2406. The window width is
taken as 40 hours, with the 2399-minute span of the two fetches as hard evidence. The firmware
accepts only one such query per connection and answers `0x02` the second time, so the probe reconnects
each time.)

### 10.4 The overlapping part is byte-for-byte identical

The two fetches overlap by 1781 minutes; comparing the 8 bytes one by one: **0 mismatches**.

This has two uses: first, parsing is deterministic and re-fetching the same minute does not drift;
second, it is safe to "fetch several times and merge" — repeated fetching will not pollute the
database, it only fills in the parts not yet covered by the window.

### 10.5 Three hard constraints on usage

1. **Sync cadence decides whether data survives.** Syncing once a day is the minimum; come back two
   days later and the first night is already outside the window.
2. **The N in `--sync-history N` only means "how far back I ask at most", not "how far back I will
   get".** What actually arrives is always ≤ 40 hours, and the app may have bitten a few holes in
   it.
3. **A hole ≠ lost data.** The hole is the app having taken it first; that segment is in the phone's
   local database, only this project cannot reach it. To judge "did we miss it", only look at
   whether the range is continuous and whether `kind` is `0xF3`; do not subtract declared counts.
