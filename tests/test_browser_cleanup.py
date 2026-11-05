from rainclass.browser import Browser

def test_close_idempotent(tmp_path):
 class Resource:
  def __init__(self):self.closed=0
  def close(self):self.closed+=1
  def stop(self):self.closed+=1
 b=Browser(tmp_path/'rainclass-edge-profile');c=Resource();p=Resource()
 b.context=c;b.pw=p;b.close();b.close()
 assert c.closed==p.closed==1

def test_close_before_open(tmp_path):
 b=Browser(tmp_path/'rainclass-edge-profile');b.close();b.close()
