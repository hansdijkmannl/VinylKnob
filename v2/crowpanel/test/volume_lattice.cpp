// Which numbers the volume may land on.
//
// Arithmetic, and so checked by arithmetic rather than by turning a knob two
// hundred times. The function under test is spliced in from settings.cpp by
// run.sh rather than copied here: the first version of this file did keep its
// own copy, the two drifted within the hour, and it cheerfully passed on code
// that was not running anywhere.
//
//     v2/crowpanel/test/run.sh
#include <cstdint>
#include <cstdio>
#include <cmath>

enum VolumeLattice : uint8_t { VOL_ANY = 0, VOL_WHOLE, VOL_EVEN, VOL_ODD, VOL_LATTICES };

__VOLUME_SNAP__

static int fails = 0;
static double db(int16_t h) { return h / 2.0 - 80.0; }
static void want(int16_t from, int dir, uint8_t lat, double expect, const char *why) {
  const double got = db(volumeSnap(from, dir, lat));
  const bool ok = std::fabs(got - expect) < 0.01;
  if (!ok) fails++;
  printf("  %s %+d from %.1f -> %.1f  (%s)\n", ok ? "ok  " : "FAIL", dir, db(from), got, why);
  if (!ok) printf("       expected %.1f\n", expect);
}

int main() {
  const int16_t at41 = 78;      // -41.0 dB
  const int16_t at405 = 79;     // -40.5 dB
  const int16_t at40 = 80;      // -40.0 dB

  printf("whole decibels only\n");
  want(at41,  +1, VOL_WHOLE, -40.0, "up a whole one, never a half");
  want(at41,  -1, VOL_WHOLE, -42.0, "and down a whole one");
  want(at405, +1, VOL_WHOLE, -40.0, "starting off the lattice: up to the nearest, not past it");
  want(at405, -1, VOL_WHOLE, -41.0, "and down to the nearest below");

  printf("even decibels only\n");
  want(at40,  +1, VOL_EVEN, -38.0, "on an even one, so a whole two up");
  want(at40,  -1, VOL_EVEN, -42.0, "and two down");
  want(at41,  +1, VOL_EVEN, -40.0, "from an odd one, up to the even above it");
  want(at41,  -1, VOL_EVEN, -42.0, "and the even below");
  want(at405, +1, VOL_EVEN, -40.0, "from a half, up to the even above");

  printf("odd decibels only\n");
  want(at41,  +1, VOL_ODD, -39.0, "on an odd one, so two up");
  want(at41,  -1, VOL_ODD, -43.0, "and two down");
  want(at40,  +1, VOL_ODD, -39.0, "from an even one, up to the odd above");
  want(at40,  -1, VOL_ODD, -41.0, "and the odd below");

  printf("above zero, where the sign flips\n");
  want(162, +1, VOL_EVEN, 2.0, "+1.0 up to the even above, not down");
  want(162, -1, VOL_EVEN, 0.0, "and down to zero, which is even");
  want(160, -1, VOL_ODD, -1.0, "0.0 down to the odd below");

  printf("and it always moves\n");
  int moved = 1;
  for (uint8_t lat = 1; lat < VOL_LATTICES; lat++)
    for (int16_t h = 0; h <= 196; h++)
      for (int d = -1; d <= 1; d += 2) {
        const int16_t out = volumeSnap(h, d, lat);
        if (out == h || (d > 0 && out <= h) || (d < 0 && out >= h)) moved = 0;
      }
  printf("  %s every value on every lattice moves, and in the direction asked\n",
         moved ? "ok  " : "FAIL");
  if (!moved) fails++;

  printf("\n%s\n", fails ? "FAILURES" : "all good");
  return fails ? 1 : 0;
}
