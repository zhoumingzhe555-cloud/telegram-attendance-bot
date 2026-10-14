import ast
import asyncio
import re
import unittest
from datetime import datetime, time, timedelta, timezone
from html import escape
from pathlib import Path
from types import SimpleNamespace

source = (Path(__file__).resolve().parents[1] / 'main.py').read_text()
tree = ast.parse(source)
keep = {'normalize', 'call_start', 'call_totals', 'call_report_text', 'business_date', 'handle_message', 'report_text', 'parse_hm'}
ns = dict(re=re, escape=escape, datetime=datetime, time=time, timedelta=timedelta,
          TZ_CHINA=timezone(timedelta(hours=8)), TRAD_MAP={'語音':'语音','視頻':'视频','號AI室':'号AI室'})
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in keep], type_ignores=[]), 'main.py', 'exec'), ns)

class CallTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {'rooms':['1号AI室','2号AI室'], 'items':{'语音':'语音','视频':'视频','回':'回'},
                    'start':'09:55','end':'02:00','timeout_limits':{},'count_limits':{},'group_count_limits':{}}
        self.rows = {}
        self.replies = []
        ns.update(get_cfg=lambda cid:self.cfg, chat_id_str=lambda u:str(u.effective_chat.id),
                  remember_chat=lambda cid:None, read_rows=lambda cid:[['header']]+self.rows.get(cid, []),
                  active_rooms=lambda *a:{}, remove_queue=lambda *a:None,
                  today_count=lambda *a:0, HOURLY=SimpleNamespace(record=lambda *a:None, members=lambda cid:[]))
        ns['append_row'] = lambda cid, row:self.rows.setdefault(cid, []).append(list(map(str,row)))

    def send(self, text, mid=1, cid='a', uid=1):
        async def reply(*a, **kw): self.replies.append(a[0])
        update = SimpleNamespace(message=SimpleNamespace(text=text, message_id=mid, reply_text=reply),
                                 effective_user=SimpleNamespace(id=uid, full_name='Alex'),
                                 effective_chat=SimpleNamespace(id=cid))
        context = SimpleNamespace(job_queue=SimpleNamespace(get_jobs_by_name=lambda n:[]))
        asyncio.run(ns['handle_message'](update, context))

    def test_start_forms(self):
        for text, kind in [('语音','语音'),('視頻','视频'),('報備語音','语音'),
                           ('2號AI室視頻\n备注：语音结束','视频'),('视频\n备注：语音','视频')]:
            self.assertEqual(ns['call_start'](text,self.cfg),kind)

    def test_end_and_summary_not_counted(self):
        for text in ['语音结束：用时60分钟\n主要内容：打语音\n客户反馈：视频',
                     '视频结束用时39分钟','語音結束','语音：已完成','视频取消','2号AI室视频结束',
                     '主要内容：打语音','回\n语音']:
            self.assertIsNone(ns['call_start'](text,self.cfg))
        self.send('语音结束：用时60分钟\n主要内容：打语音')
        self.send('2号AI室视频结束',2)
        self.assertEqual(self.rows,{})

    def test_identity_isolation_duplicate_and_daily_report(self):
        self.send('语音',1)
        self.send('语音',1)
        self.send('2号AI室视频\n备注',2)
        self.send('视频',3,uid=2)
        self.send('语音',1,cid='b')
        day=ns['business_date'](datetime.now(ns['TZ_CHINA']))
        self.assertEqual(ns['call_totals']('a',day),{'1':{'语音':1,'视频':1},'2':{'语音':0,'视频':1}})
        self.assertEqual(ns['call_totals']('b',day),{'1':{'语音':1,'视频':0}})
        self.assertIn('开始报备：语音1次、视频1次',ns['report_text']('a',self.cfg))
        self.assertIn('全群合计：语音1次，视频2次',ns['call_report_text']('a'))
        self.assertIn('今日开始报备',self.replies[0])
        self.rows.clear()
        self.assertEqual(ns['call_totals']('a',day),{})

    def test_busy_room_does_not_count(self):
        ns['active_rooms']=lambda *a:{'2号AI室':{'uid':'99','name':'Other'}}
        self.send('2号AI室视频')
        self.assertEqual(self.rows,{})

    def test_old_rows_not_backfilled(self):
        day=ns['business_date'](datetime.now(ns['TZ_CHINA']))
        self.rows['a']=[['now',day,'1','Alex','语音','1','正常','N/A','']]
        self.assertEqual(ns['call_totals']('a',day),{})

    def test_midnight_business_date(self):
        at=datetime(2026,10,14,1,tzinfo=ns['TZ_CHINA'])
        self.assertEqual(ns['business_date'](at),'2026-10-13')

if __name__ == '__main__':
    unittest.main()
