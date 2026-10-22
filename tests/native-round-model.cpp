#include "../xiaozhi-firmware/main/boards/round-voice-175c/round_model.h"
#include <cassert>
int main() {
    using namespace round_voice;
    for (auto r : kHomeTiles) {
        for (int x : {r.x, r.x+r.w}) for (int y : {r.y, r.y+r.h})
            assert((x-233)*(x-233)+(y-233)*(y-233) <= 219*219);
    }
    assert(ClampVolume(-1)==0 && ClampVolume(101)==100);
    assert(ClampBrightness(0)==5 && ClampBrightness(101)==100);
    assert(!ValidWeather({0,0,0,0,false}));
    assert(ValidWeather({23.5,65,8,2,true}));
    assert(!ValidWeather({23.5,165,8,2,true}));
    assert(!ValidWeather({23.5,65,-8,2,true}));
    assert(ValidCity(0) && !ValidCity(-1) && !ValidCity(kCityCount));
}
