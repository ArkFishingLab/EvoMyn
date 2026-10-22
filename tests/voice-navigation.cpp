#include "../xiaozhi-firmware/main/boards/round-voice-175c/voice_navigation.h"
#include <cassert>
int main(){
    using namespace round_voice;
    assert(VoiceDestination(false,false,kDeviceStateWifiConfiguring)==VoiceRoute::Wifi);
    assert(VoiceDestination(true,false,kDeviceStateActivating)==VoiceRoute::Agent);
    assert(VoiceDestination(true,true,kDeviceStateWifiConfiguring)==VoiceRoute::Agent);
    assert(VoiceDestination(true,true,kDeviceStateIdle)==VoiceRoute::Chat);
    assert(VoiceDestination(true,true,kDeviceStateSpeaking)==VoiceRoute::Chat);
    assert(VoiceDestination(true,true,kDeviceStateConnecting)==VoiceRoute::Wait);
    int step=0;
    EndConversationActions(kDeviceStateSpeaking,[&]{assert(step++==0);},[&]{assert(step++==2);},[&]{assert(step++==1);});
    assert(step==3);step=1;
    EndConversationActions(kDeviceStateConnecting,[&]{assert(false);},[&]{assert(step++==2);},[&]{assert(step++==1);});
    assert(step==3);step=0;
    EndConversationActions(kDeviceStateActivating,[&]{++step;},[&]{++step;},[&]{++step;});assert(step==0);
}
