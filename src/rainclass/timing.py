"""Countdown policy independent of browser and Qt; no real-platform actions."""
import math,time
from .core import Countdown
class TimingPolicy:
 def __init__(self,threshold=10,reminders=(30,20,10)):
  self.clock=Countdown();self.instance=None;self.alerted=set();self.mode='review'
  self.threshold=max(1,min(60,int(threshold)));self.reminders=sorted({int(x) for x in reminders if 0<int(x)<=3600},reverse=True)
 def observe(self,s):
  q=s.get('question') or {};ident=q.get('id')
  if ident is not None and ident!=self.instance:self.instance=ident;self.alerted.clear()
  deadline=q.get('deadline');fresh=s.get('observed_at')
  valid=(s.get('online',False) and s.get('course_active') and not q.get('closed') and not q.get('submitted') and isinstance(deadline,(int,float)) and math.isfinite(deadline) and isinstance(fresh,(int,float)) and 0<=time.time()-fresh<=3)
  self.clock.sync(max(0,deadline-time.time()) if valid else None)
  remaining=self.clock.remaining();alerts=[]
  if remaining is not None and remaining>0:
   for threshold in self.reminders:
    if remaining<=threshold and threshold not in self.alerted:
     self.alerted.add(threshold);alerts.append(threshold)
  return remaining,alerts
 def should_submit(self,result,remaining,reviewed=False):
  if not result or result.get('question_instance_id')!=self.instance or remaining is None or remaining<=0:return False
  return reviewed or self.mode=='auto' or (self.mode=='smart' and remaining<=self.threshold)
