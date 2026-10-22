import os,shlex,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
class LocalAlertAudioTest(unittest.TestCase):
 def test_builtin_chime_fits_nonblocking_decode_queue(self):
  raw=(ROOT/'main/assets/common/success.ogg').read_bytes();pos=0;packet=bytearray();packets=[];granule=0
  while pos<len(raw):
   self.assertEqual(raw[pos:pos+4],b'OggS')
   count=raw[pos+26];lengths=raw[pos+27:pos+27+count];payload=pos+27+count;granule=int.from_bytes(raw[pos+6:pos+14],'little')
   for size in lengths:
    packet.extend(raw[payload:payload+size]);payload+=size
    if size<255:packets.append(bytes(packet));packet.clear()
   pos=payload
  audio=[p for p in packets if not p.startswith((b'OpusHead',b'OpusTags'))]
  self.assertLessEqual(len(audio),20)
  self.assertLessEqual(granule/48000,1.2)
 def test_actual_queue_rejects_remote_packets_and_unblocks_cancelled_producer(self):
  source=(ROOT/'main/audio/audio_service.cc').read_text(encoding='utf-8')
  start=source.index('bool AudioService::PushPacketToDecodeQueue(')
  end=source.index('std::unique_ptr<AudioStreamPacket> AudioService::PopPacketFromSendQueue',start)
  body=source[start:end].replace('AudioService::','Harness::')
  pre=r"""
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <memory>
#include <mutex>
#include <thread>
constexpr int MAX_DECODE_PACKETS_IN_QUEUE=2;
struct AudioStreamPacket{};
struct Harness{
 std::mutex audio_queue_mutex_;std::condition_variable audio_queue_cv_;
 std::deque<std::unique_ptr<AudioStreamPacket>> audio_decode_queue_;
 std::atomic<bool> service_stopped_{false},local_alert_active_{false};
 uint32_t playback_generation_=0;bool playback_drained_notified_=true;
 bool PushPacketToDecodeQueue(std::unique_ptr<AudioStreamPacket>,bool=false,bool=false);
};
"""
  main=r"""
int main(){
 Harness h;
 assert(h.PushPacketToDecodeQueue(std::make_unique<AudioStreamPacket>()));
 assert(h.PushPacketToDecodeQueue(std::make_unique<AudioStreamPacket>()));
 std::atomic<bool> started{false};bool accepted=true;
 std::thread waiting([&]{started=true;accepted=h.PushPacketToDecodeQueue(std::make_unique<AudioStreamPacket>(),true);});
 while(!started)std::this_thread::yield();
 std::this_thread::sleep_for(std::chrono::milliseconds(20));
 {std::lock_guard<std::mutex> lock(h.audio_queue_mutex_);h.local_alert_active_=true;h.audio_decode_queue_.clear();++h.playback_generation_;}
 h.audio_queue_cv_.notify_all();waiting.join();assert(!accepted);
 assert(!h.PushPacketToDecodeQueue(std::make_unique<AudioStreamPacket>()));
 assert(h.PushPacketToDecodeQueue(std::make_unique<AudioStreamPacket>(),false,true));
 h.local_alert_active_=false;
 assert(!h.PushPacketToDecodeQueue(std::make_unique<AudioStreamPacket>(),false,true));
 assert(h.PushPacketToDecodeQueue(std::make_unique<AudioStreamPacket>()));
}
"""
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory);cc=path/'audio.cc';exe=path/('audio.exe' if os.name=='nt' else 'audio')
   cc.write_text(pre+body+main,encoding='utf-8')
   subprocess.run(shlex.split(os.environ.get('CXX','c++'))+['-std=c++17','-Wall','-Wextra','-Werror','-pthread',str(cc),'-o',str(exe)],check=True)
   subprocess.run([exe],check=True,timeout=10)
