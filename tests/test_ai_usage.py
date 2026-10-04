import ast, asyncio, csv, tempfile, unittest
from pathlib import Path
from datetime import datetime, time, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
source=(Path(__file__).resolve().parents[1] / 'main.py').read_text()
compile(source, 'main.py', 'exec')
tree=ast.parse(source)
keep={'parse_hm','ai_usage_sessions','ai_usage_text','send_ai_usage','normalize','scheduler'}
ns=dict(datetime=datetime,time=time,timedelta=timedelta,TZ_CHINA=timezone(timedelta(hours=8)),BytesIO=BytesIO,TRAD_MAP={})
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in keep],type_ignores=[]),'main.py','exec'),ns)
class UsageTests(unittest.TestCase):
 def setUp(self):
  self.rows={}; ns['read_rows']=lambda cid:[['header']]+self.rows.get(cid,[])
  self.cfg={'reset':'05:05','rooms':['1号AI室','2号AI室']}
  self.now=datetime(2026,10,5,2,tzinfo=ns['TZ_CHINA'])
 def row(self,at,action,uid='1',marker=''):
  return [at,'date',uid,'A <&>',action,1,'正常','N/A',marker]
 def test_return_and_midnight(self):
  self.rows['a']=[self.row('2026-10-04 23:50:00','1号AI室'),self.row('2026-10-05 00:10:00','回')]
  s=ns['ai_usage_sessions']('a',self.cfg,self.now)[1]
  self.assertEqual((s[0]['end']-s[0]['start']).total_seconds(),1200)
 def test_repeat_switch_off_and_active(self):
  self.rows['a']=[self.row('2026-10-04 10:00:00','1号AI室'),self.row('2026-10-04 10:01:00','1号AI室'),self.row('2026-10-04 10:10:00','2号AI室'),self.row('2026-10-04 10:15:00','下班'),self.row('2026-10-04 11:00:00','1号AI室')]
  s=ns['ai_usage_sessions']('a',self.cfg,self.now)[1]
  self.assertEqual(len(s),3);self.assertEqual(s[0]['reason'],'换房');self.assertEqual(s[1]['reason'],'下班');self.assertIsNone(s[2]['end'])
 def test_reset_and_isolation(self):
  self.rows['a']=[self.row('2026-10-04 05:04:59','1号AI室'),self.row('2026-10-04 05:05:00','2号AI室')]
  self.assertEqual(len(ns['ai_usage_sessions']('a',self.cfg,self.now)[1]),1)
  self.assertEqual(ns['ai_usage_sessions']('b',self.cfg,self.now)[1],[])
  later=self.now.replace(hour=5,minute=5)
  self.assertEqual(ns['ai_usage_sessions']('a',self.cfg,later)[1],[])
 def test_deleted_room_marker_and_malformed(self):
  self.rows['a']=[['bad'], self.row('bad','1号AI室'),self.row('2026-10-04 10:00:00','自定义室',marker='AI室')]
  self.assertEqual(ns['ai_usage_sessions']('a',self.cfg,self.now)[1][0]['room'],'自定义室')
 def test_aliases(self):
  for value in ['AI室记录','ai 室記錄','AI室紀錄']:
   self.assertEqual(ns['normalize'](value,self.cfg),'AI室记录')
 def test_delivery(self):
  sent=[]
  async def message(**kw):sent.append(kw)
  async def document(**kw):sent.append(kw['document'].getvalue())
  bot=SimpleNamespace(send_message=message,send_document=document)
  original=ns['ai_usage_text']
  try:
   ns['ai_usage_text']=lambda *a:'A <&>'
   asyncio.run(ns['send_ai_usage'](bot,'a',1,self.cfg));self.assertIsNone(sent[0]['parse_mode'])
   ns['ai_usage_text']=lambda *a:'测试'*2000
   asyncio.run(ns['send_ai_usage'](bot,'a',1,self.cfg));self.assertTrue(sent[1].startswith(b'\xef\xbb\xbf'))
  finally:ns['ai_usage_text']=original
unittest.main()
