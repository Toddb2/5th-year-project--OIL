# TTC001 loop tuning

Step of 1 C around 25 C, 120 s recorded per setting. Laser off.

| Gains (P, I, D) | Settling time | Swing, last minute (C) | Offset (C) | RMS TEC current (mA) | |
|---|---|---|---|---|---|
| 5, 1, 60 | never | 3.714 | 1.314 | 454 |  |
| 8, 2, 30 | never | 3.727 | 0.307 | 453 |  |
| 5, 1, 20 | never | 3.939 | 1.251 | 454 |  |
| 3, 1, 10 | never | 3.650 | 0.228 | 454 | **best** |
| 2, 1, 5 | never | 3.859 | 1.206 | 454 |  |
| 1, 0.5, 0 | never | 3.769 | 0.140 | 454 |  |

Best: P 3, I 1, D 10 (still swings; heatsinking is the next thing to check). Left on the TTC001.

Put the same numbers into Kinesis (TTC001 Settings -> Advanced) on BOTH the Current and Startup tabs and press Save, or Kinesis restores its own gains next time it opens.
