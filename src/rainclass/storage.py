import sqlite3,json,threading,time
class Store:
 def __init__(self,path):
  self.db=sqlite3.connect(str(path),check_same_thread=False);self.lock=threading.RLock()
  with self.db:
   self.db.execute('PRAGMA journal_mode=WAL')
   self.db.executescript("""CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY,result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,created REAL,course TEXT,instance TEXT,result TEXT);
CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY,created REAL,course TEXT,model TEXT,status TEXT,input_tokens INTEGER,output_tokens INTEGER,hit INTEGER,miss INTEGER,cost REAL,reserved REAL,duration_ms REAL);""")
 def cached(self,key):
  with self.lock:
   row=self.db.execute('SELECT result FROM cache WHERE key=?',(key,)).fetchone()
   return json.loads(row[0]) if row else None
 def save(self,key,q,result,persist=True):
  if not persist:return
  with self.lock,self.db:
   text=json.dumps(result,ensure_ascii=False)
   self.db.execute('INSERT OR REPLACE INTO cache VALUES (?,?)',(key,text))
   self.db.execute('INSERT INTO history(created,course,instance,result) VALUES (?,?,?,?)',(time.time(),q.course_id,q.instance_id,text))
 def record(self,q,model,status,usage,duration,profile):
  def count(k):
   v=usage.get(k);return v if isinstance(v,int) and not isinstance(v,bool) and v>=0 else None
  inp,out,hit,miss=[count(k) for k in ('prompt_tokens','completion_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens')]
  cost=None
  if inp is not None and out is not None and 'input_price' in profile and 'output_price' in profile:
   cost=(inp*float(profile['input_price'])+out*float(profile['output_price']))/1_000_000
  with self.lock,self.db:self.db.execute('INSERT INTO usage(created,course,model,status,input_tokens,output_tokens,hit,miss,cost,reserved,duration_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(time.time(),q.course_id,model,status,inp,out,hit,miss,cost,float(profile.get('max_request_cost',0.1)),duration))
 def allowance(self,course,limit,budget,reserve):
  with self.lock:
   count,spent=self.db.execute('SELECT COUNT(*),COALESCE(SUM(MAX(COALESCE(cost,0),reserved)),0) FROM usage WHERE course=?',(course,)).fetchone()
   return (limit is None or count<limit) and (budget is None or spent+reserve<=budget+1e-9)
 def history(self):
  with self.lock:return [json.loads(x[0]) for x in self.db.execute('SELECT result FROM history ORDER BY id DESC LIMIT 100')]
 def summary(self):
  with self.lock:
   self.db.row_factory=sqlite3.Row
   rows=[dict(x) for x in self.db.execute('SELECT model,status,COUNT(*) requests,SUM(input_tokens) input_tokens,SUM(output_tokens) output_tokens,SUM(hit) cache_hit_tokens,SUM(miss) cache_miss_tokens,SUM(cost) estimated_cost FROM usage GROUP BY model,status')]
   self.db.row_factory=None;return rows
 def clear(self,include_usage=False):
  with self.lock,self.db:
   self.db.execute('DELETE FROM cache');self.db.execute('DELETE FROM history')
   if include_usage:self.db.execute('DELETE FROM usage')
 def close(self):self.db.close()
