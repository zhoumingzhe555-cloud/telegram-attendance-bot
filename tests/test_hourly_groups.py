import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hourly_groups import HourlyGroups, TZ, ROSTER, hour

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'groups.db'
        self.store = HourlyGroups(self.path)
        self.at = datetime(2026, 10, 10, 10, 0, tzinfo=TZ)
        self.store.initialize('1', self.at)
        self.store.set_member('1', '金花组', '金圣', '100')

    def tearDown(self):
        self.tmp.cleanup()

    def event(self, mid, action='wc小', uid='100', at=None):
        self.store.record('1', mid, at or self.at, uid, '改过的昵称', action)

    def test_roster_and_reinit(self):
        self.assertEqual([len(x) for x in ROSTER.values()], [12,12,12,11])
        self.store.remove('1', name='AK')
        self.assertFalse(self.store.initialize('1', self.at))
        self.assertEqual(len(self.store.members('1')),46)
        self.assertEqual(HourlyGroups(self.path).members('1'),self.store.members('1'))

    def test_actions_dedupe_and_boundaries(self):
        for i,a in enumerate(['wc小','wc大','抽烟','吃饭','1号AI室']): self.event(i,a)
        self.event(0)
        self.event(9,at=self.at + timedelta(hours=1))
        text = self.store.report('1',hour(self.at),hour(self.at)+3600)
        self.assertIn('金圣3',text)
        self.assertIn('全群合计：3次',text)
        self.assertNotIn('金圣3', self.store.report('2',hour(self.at),hour(self.at)+3600))

    def test_no_guessing_unknown_and_bind(self):
        self.event(1,uid='200')
        self.assertIn('未分组',self.store.report('1',hour(self.at),hour(self.at)+3600))
        self.store.set_member('1','杨逍组','大海','200')
        self.assertIn('大海1',self.store.report('1',hour(self.at),hour(self.at)+3600))
        with self.assertRaises(ValueError):self.store.set_member('1','金花组','金圣','200')

    def test_move_delete_keeps_event_team(self):
        self.event(1)
        self.store.set_member('1','杨逍组','金圣','100')
        self.event(2)
        self.store.remove('1',uid='100')
        text=self.store.report('1',hour(self.at),hour(self.at)+3600)
        self.assertEqual(text.count('金圣1'),2)
        self.assertIn('全群合计：2次',text)

    def test_retry_restart_and_purge(self):
        self.event(1)
        messages=[]
        async def fail(**kw):raise RuntimeError('offline')
        asyncio.run(self.store.tick(SimpleNamespace(send_message=fail),self.at+timedelta(hours=1)))
        async def send(**kw):messages.append(kw['text'])
        bot=SimpleNamespace(send_message=send)
        restored=HourlyGroups(self.path)
        asyncio.run(restored.tick(bot,self.at+timedelta(hours=1)))
        asyncio.run(restored.tick(bot,self.at+timedelta(hours=1,minutes=1)))
        self.assertEqual(len(messages),1)
        self.assertIn('金圣1',messages[0])
        with restored.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
        self.assertEqual(len(restored.members('1')),47)

    def test_reset_midnight_and_retention(self):
        start=datetime(2026,10,10,5,tzinfo=TZ)
        self.event(1,at=start+timedelta(minutes=1))
        self.event(2,at=start+timedelta(minutes=6))
        self.assertIn('金圣2',self.store.report('1',hour(start),hour(start)+3600))
        async def fail(**kw):raise RuntimeError('offline')
        asyncio.run(self.store.tick(SimpleNamespace(send_message=fail),start+timedelta(days=2)))
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)

    def test_admin_only(self):
        replies=[]
        async def reply(text):replies.append(text)
        async def member(*args):return SimpleNamespace(status='member')
        msg=SimpleNamespace(sender_chat=None,reply_text=reply,text='/initgroups')
        u=SimpleNamespace(effective_chat=SimpleNamespace(id=2,type='supergroup'),effective_user=SimpleNamespace(id=8),effective_message=msg)
        asyncio.run(self.store.command(u,SimpleNamespace(bot=SimpleNamespace(get_chat_member=member),args=[])))
        self.assertIn('只有群管理员',replies[0]);self.assertEqual(self.store.members('2'),[])

    def test_work_hours_and_final_report(self):
        messages=[]
        async def send(**kw): messages.append(kw['text'])
        bot=SimpleNamespace(send_message=send)
        self.event(1,at=datetime(2026,10,11,1,30,tzinfo=TZ))
        asyncio.run(self.store.tick(bot,datetime(2026,10,11,2,0,20,tzinfo=TZ)))
        self.assertEqual(len(messages),1)
        self.assertIn('金圣1',messages[0])
        asyncio.run(self.store.tick(bot,datetime(2026,10,11,3,0,tzinfo=TZ)))
        asyncio.run(self.store.tick(bot,datetime(2026,10,11,9,0,tzinfo=TZ)))
        self.assertEqual(len(messages),1)

    def test_morning_unique_counts_and_once(self):
        messages=[]
        async def send(**kw): messages.append(kw['text'])
        bot=SimpleNamespace(send_message=send)
        opening=datetime(2026,10,11,9,55,tzinfo=TZ)
        self.event(1,action='上班',at=opening-timedelta(minutes=5))
        self.event(2,action='上班',at=opening-timedelta(minutes=2))
        self.event(3,action='上班',uid='999',at=opening-timedelta(minutes=1))
        self.event(4,action='上班',uid='888',at=opening-timedelta(days=1))
        asyncio.run(self.store.tick(bot,opening))
        asyncio.run(HourlyGroups(self.path).tick(bot,opening+timedelta(seconds=30)))
        self.assertEqual(len(messages),1)
        self.assertIn('金花组：已打卡1人／名单12人',messages[0])
        self.assertIn('未分组已打卡：1人',messages[0])
        self.assertIn('全群已打卡：2人',messages[0])

    def test_partial_hour_and_custom_schedule(self):
        messages=[]
        async def send(**kw): messages.append(kw['text'])
        cfg=lambda cid:dict(start='10:15',end='11:20',reset='05:05')
        bot=SimpleNamespace(send_message=send)
        self.event(1,at=self.at+timedelta(minutes=5))
        self.event(2,at=self.at+timedelta(minutes=20))
        asyncio.run(self.store.tick(bot,self.at+timedelta(hours=1),get_cfg=cfg))
        self.assertIn('10:15—10-10 11:00',messages[0])
        self.assertIn('金圣1',messages[0])
        self.event(3,at=self.at+timedelta(hours=1,minutes=10))
        asyncio.run(self.store.tick(bot,self.at+timedelta(hours=1,minutes=20),get_cfg=cfg))
        self.assertIn('11:00—10-10 11:20',messages[1])
        self.assertIn('金圣1',messages[1])

if __name__=='__main__': unittest.main()
