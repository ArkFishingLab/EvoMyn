#include "../xiaozhi-firmware/main/boards/round-voice-175c/round_model.h"
#include <cassert>
int main() {
    using namespace round_voice;
    assert(kHomeTiles[0].x == 174 && kHomeTiles[0].y == 193);
    assert(kHomeTiles[0].w == 118 && kHomeTiles[0].h == 118);
    assert(kHomeTiles[1].x == 159 && kHomeTiles[1].y == 358);
    assert(kSettingsControls[0].x == 87 && kSettingsControls[0].y == 154);
    assert(kSettingsControls[1].y == 211);
    for (auto r : kHomeTiles)
        for (int x : {r.x,r.x+r.w}) for (int y : {r.y,r.y+r.h})
            assert((x-233)*(x-233)+(y-233)*(y-233) <= 219*219);
}
