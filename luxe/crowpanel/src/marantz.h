#pragma once

#include <Arduino.h>

// Volume wordt overal in halve stappen bijgehouden: 0..196.
//   dB = halfSteps / 2.0 - 80.0
struct AvrState {
  bool     connected    = false;
  bool     powered      = false;   // hoofdzone aan
  bool     muted        = false;
  bool     haveVolume   = false;
  int      volHalfSteps = 0;
  int      volMaxHalf   = 196;     // wordt overschreven door MVMAX
  char     input[24]    = "?";     // protocolcode zoals de AVR hem meldt
  char     inputLabel[24] = "?";   // jouw label, als de code in de knoppen zit
  uint32_t revision     = 0;       // loopt op bij elke wijziging
};

extern AvrState avrState;

void avrLoop();

// Stuurt een ruw commando ("SIPHONO", "MV?"). False als er geen verbinding is.
bool avrSend(const char *cmd);

// Zet het volume. Wordt gethrottled in avrLoop, dus je mag dit bij elke klik
// aanroepen zonder de receiver te verzuipen.
void avrSetVolumeHalf(int halfSteps);

// Waar het volume op ophoudt: het laagste van MVMAX en jouw eigen plafond.
int avrVolumeCeilingHalf();

// Het volume waar we naartoe onderweg zijn (of de huidige stand als er niets
// in de wachtrij staat).
int avrPendingVolumeHalf();

// Gooit de verbinding weg zodat avrLoop opnieuw verbindt. Gebruik dit nadat
// het IP van de receiver is gewijzigd.
void avrReconnect();

// Loopt op bij elk verzonden commando; de status-LED knippert hierop.
uint32_t avrTxCount();
