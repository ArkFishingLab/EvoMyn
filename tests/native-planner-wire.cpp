#include "planner_wire.h"
#include <cassert>
#include <string>
using namespace round_voice;
int main() {
    PlannerModel model;std::string error;
    PlannerSnapshot value{1,1792154320,{{"t1","回电话","正文","task","pending",1,1792154380}},{{"o1","t1","回电话",1,1792154380}},false};
    assert(model.Apply(value,error));
    model.TakeDue(1792154380,"op-fired");
    model.Enqueue({"op-snooze","snooze","t1","o1",1,1792154980},error);
    auto cache=EncodePlannerCache(model);assert(!cache.empty());
    PlannerModel restored;
    assert(DecodePlannerCache(cache,restored,error));
    assert(restored.pending().size()==2 && restored.fired().size()==1);
    assert(restored.Effective().reminders[0].id=="snooze-op-snooze");
    auto action=EncodePlannerAction(restored.pending()[1]);
    assert(action.find("1792154980")!=std::string::npos);
    assert(action.find("accepted_revision")==std::string::npos);
    restored.Result("op-snooze",true,2);
    PlannerModel accepted;
    assert(DecodePlannerCache(EncodePlannerCache(restored),accepted,error));
    assert(accepted.Effective().reminders[0].id=="snooze-op-snooze");
    auto ack=EncodePlannerAck(value);assert(ack.find("o1")!=std::string::npos);
    PlannerMessage message;
    assert(DecodePlannerMessage(R"({"type":"snapshot","revision":2,"server_time":1792154320,"tasks":[],"reminders":[],"truncated":false})",message,error));
    assert(message.snapshot.revision==2);
    assert(DecodePlannerMessage(R"({"type":"result","op_id":"op-snooze","ok":true,"revision":2})",message,error));
    assert(message.ok && message.revision==2);
    assert(DecodePlannerMessage(R"({"type":"result","op_id":"op-snooze","ok":false,"error":"conflict"})",message,error));
    assert(!message.ok && message.error=="conflict");
    assert(!DecodePlannerMessage("{\"type\":\"result\",\"op_id\":\"op-snooze\",\"ok\":false,\"error\":\""+std::string(193,'x')+"\"}",message,error));
    for(const auto& bad: {std::string(65537,'x'),std::string("{} trailing"),
       std::string(R"({"type":"snapshot","revision":1.5,"server_time":1792154320,"tasks":[],"reminders":[]})"),
       std::string(R"({"type":"snapshot","revision":1,"server_time":0,"tasks":[],"reminders":[]})"),
       std::string(R"({"type":"result","op_id":"bad\nid","ok":true,"revision":2})")})
       assert(!DecodePlannerMessage(bad,message,error));
    std::string nested(40,'[');nested+='0';nested+=std::string(40,']');
    assert(!DecodePlannerMessage(nested,message,error));
    // A crash-safe local settings cache is valid even before first network sync.
    PlannerModel empty;empty.SetVolume(0);
    assert(DecodePlannerCache(EncodePlannerCache(empty),restored,error));
    assert(restored.volume()==0 && restored.base().tasks.empty());
    assert(!DecodePlannerCache("{bad",restored,error));
    PlannerModel cancelled;assert(cancelled.Apply(value,error));
    assert(cancelled.Enqueue({"cancel-offline","cancel","t1","",1,0},error));
    assert(DecodePlannerCache(EncodePlannerCache(cancelled),restored,error));
    assert(restored.Effective().tasks[0].status=="cancelled");
    assert(restored.Effective().reminders.empty());
    assert(EncodePlannerAction(restored.pending()[0]).find("\"cancel\"")!=std::string::npos);
}
