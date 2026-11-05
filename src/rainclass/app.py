import sys, time, json, logging, os, tomllib, math
from pathlib import Path
from threading import Event
from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QTextEdit, QComboBox, QSystemTrayIcon, QMenu, QStyle, QCheckBox, QTabWidget
from .mock import Server
from .browser import Browser, MockAdapter
from .core import Monitor
from .timing import TimingPolicy
from .diagnostics import Diagnostics
from .storage import Store
from .presentation import question_text, result_text, usage_text, STATES
from .analysis import AnalysisService
from .ai import FakeAI, CompatibleAI, AnalysisError

class Worker(QThread):
    update=Signal(str)
    question=Signal(str)
    new_question=Signal(str)
    countdown=Signal(str)
    alert=Signal(str)
    def __init__(self, url, profile, headless, interval, ai_config=None):
        super().__init__(); self.url=url; self.profile=profile; self.headless=headless; self.interval=interval
        self.stopping=Event(); self.paused=Event(); self.monitor=Monitor()
        self.ai_config=ai_config or {}; self.futures=[]; self.ai_errors=0
        self.reanalyze=Event(); self.latest_question=None; self.question_context={}
        self.mode="review"; self.review_request=Event(); self.results={}; self.attempted=set(); self.timing=TimingPolicy(**self.ai_config.get('timing',{}))
    def run(self):
        store=Store(self.profile.parent/'analysis.sqlite3')
        profiles=self.ai_config.get('profiles',[]) if self.ai_config.get('cloud_enabled',False) else []
        try:
            clients=[CompatibleAI(p) for p in profiles[:2]] or [FakeAI()]
            service=AnalysisService(store,clients,persist=self.ai_config.get('persist',True),call_limit=int(self.ai_config.get('call_limit',20)),budget=float(self.ai_config.get('budget',1.0)))
            self._monitor(service)
        except Exception as e:
            self.update.emit('分析初始化失败：'+type(e).__name__)
        finally:
            if 'service' in locals():service.close()
            store.close()
    def _monitor(self,service):
        failures=0
        while not self.stopping.is_set() and failures<4:
            browser=Browser(self.profile,self.headless)
            try:
                page=browser.open(self.url+"/student"); adapter=MockAdapter(self.url)
                last=None
                diagnostic=Diagnostics(self.profile.parent/"mock-diagnostics.jsonl")
                while not self.stopping.is_set():
                    if self.paused.is_set(): self.stopping.wait(.2); continue
                    s=adapter.snapshot(page); state,q=self.monitor.observe(s)
                    self.timing.mode=self.mode
                    remaining,alerts=self.timing.observe(s)
                    self.countdown.emit('剩余时间未知/题目已关闭' if remaining is None else f'剩余 {max(0,math.ceil(remaining))} 秒（模拟教师截止时间）')
                    for threshold in alerts:self.alert.emit(f'模拟课堂：剩余不足 {threshold} 秒，请审查答案。')
                    diagnostic.sample(page,course_state="IDLE_NO_CLASS" if not s.get("course_active") else "VERIFIED_QUESTION" if s.get("question") else "IGNORE_PPT",detection=state)
                    if state == "NEEDS_MANUAL":
                        manual=self.monitor.manual_events[-1]
                        label="简答题" if manual["kind"] == "essay" else "主观题或未知题型"
                        self.new_question.emit(label)
                        self.question.emit(f"【{label}】{manual['stem']}\n需人工处理，不调用AI")
                    if q:
                        self.new_question.emit({"single":"单选题","multiple":"多选题","blank":"填空题"}.get(q.kind,"习题"))
                        self.latest_question=q
                        self.question_context[q.instance_id]=q
                        self.question.emit(question_text(q))
                        self.futures.append(service.submit(q))
                    if self.reanalyze.is_set():
                        self.reanalyze.clear()
                        if self.latest_question:
                            future=service.submit(self.latest_question,force=True)
                            if future not in self.futures:self.futures.append(future)
                    for future in self.futures[:]:
                        if future.done():
                            self.futures.remove(future)
                            try:
                                result=future.result()
                                self.results[result['question_instance_id']]=result
                                self.question.emit(result_text(result,self.question_context.get(result['question_instance_id'])))
                            except Exception as e:
                                self.ai_errors+=1
                                self.question.emit('分析失败：'+(str(e) if isinstance(e, AnalysisError) else type(e).__name__))
                    current=(s.get('question') or {}).get('id')
                    result=self.results.get(current)
                    reviewed=self.review_request.is_set();self.review_request.clear()
                    if reviewed and not result:self.question.emit('尚无当前题目的分析结果，请等待后再审查确认。')
                    if current not in self.attempted and self.timing.should_submit(result,remaining,reviewed):
                        self.attempted.add(current)
                        try:
                            receipt=adapter.submit(page,result)
                            self.question.emit('【仅本地模拟】填写并提交成功，已收到回执。')
                        except Exception:
                            self.question.emit('【仅本地模拟】提交未确认或题目已失效；为避免重复操作，不自动重试。')
                    display_state=state
                    if state == "DUPLICATE":
                        raw=s.get("question") or {}
                        display_state="需人工处理" if raw.get("type") not in ("single","multiple","blank") else "已识别，等待新题"
                    elif state == "NEEDS_MANUAL": display_state="需人工处理"
                    total=len(self.monitor.events)+len(self.monitor.manual_events)
                    text=STATES.get(display_state,display_state)+' | 分析失败 '+str(self.ai_errors)+' | 新题 '+str(total)+'（人工处理 '+str(len(self.monitor.manual_events))+'） | 云端累计请求 '+str(sum(row['requests'] for row in service.store.summary())) 
                    if text!=last: self.update.emit(text); last=text
                    self.stopping.wait(self.interval)
                return
            except Exception as e:
                failures+=1; self.update.emit(f"RECOVERING {failures}/4 ({type(e).__name__})")
                self.stopping.wait(min(2**failures,8))
            finally:
                try: browser.close()
                except Exception: pass
        if not self.stopping.is_set(): self.update.emit("恢复次数已达上限，请停止后重启")

class Window(QMainWindow):
    def __init__(self, data_dir=None):
        super().__init__(); self.setWindowTitle("RainClass · 课堂 AI 助手"); self.resize(1100,900)
        from .ui_fonts import configure_fonts
        configure_fonts(QApplication.instance())
        self.worker=None
        self.data=Path(data_dir).resolve() if data_dir else Path(os.getenv('LOCALAPPDATA',str(Path.home()))) / 'RainClassAssistant'
        self.data.mkdir(parents=True,exist_ok=True)
        self.config={}
        base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]
        cfg=base/'config.toml'
        if cfg.exists(): self.config=tomllib.loads(cfg.read_text(encoding='utf-8'))
        self.server=Server().start()
        logging.basicConfig(filename=self.data/'events.jsonl',level=logging.INFO,encoding='utf-8')
        box=QVBoxLayout(); root=QWidget();root.setLayout(box)
        self.tabs=QTabWidget();self.tabs.setStyleSheet('QTabWidget::pane {border:1px solid #dce2eb;background:#f4f6fa;} QTabBar::tab {padding:9px 22px;margin-right:3px;background:#f8fafc;border:1px solid #dce2eb;border-radius:4px;color:#23354d;} QTabBar::tab:selected {background:#2563eb;color:white;border-color:#2563eb;}');self.tabs.addTab(root,'本地模拟')
        from PySide6.QtWidgets import QHBoxLayout
        shell=QWidget();shell_box=QVBoxLayout(shell);self.notification_box=QHBoxLayout()
        shell_box.addLayout(self.notification_box);shell_box.addWidget(self.tabs);self.setCentralWidget(shell)
        self.notification_hint=QLabel();self.notification_hint.setWordWrap(True);self.notification_hint.hide()
        shell_box.insertWidget(1,self.notification_hint)
        box.addWidget(QLabel('本地模拟环境 · 默认FakeAI仅演示 · 自动提交仅限本机模拟服务 · 真实平台 NOT_VERIFIED'))
        self.cloud=QCheckBox('启用配置中的云端模型（默认关闭，停止后生效）');box.addWidget(self.cloud)
        self.cloud.setToolTip('config.toml [ai] profiles配置；Key仅从环境变量读取。')
        self.persist=QCheckBox('保存本地结果缓存与历史');self.persist.setChecked(True);box.addWidget(self.persist)
        preferences={}
        try:preferences=json.loads((self.data/'ui-preferences.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
        if not isinstance(preferences,dict):preferences={}
        self.new_question_notifications=QCheckBox('新题弹窗提醒（每检测到一题提醒一次）')
        self.new_question_notifications.setChecked(preferences.get('new_question_notifications',True) is not False)
        self.countdown_notifications=QCheckBox('倒计时弹窗提醒')
        self.countdown_notifications.setChecked(preferences.get('countdown_notifications',True) is not False)
        self.essay_sound=QCheckBox('主观题声音提醒（检测到新题时响一次）')
        self.essay_sound.setChecked(preferences.get('essay_sound',True) is not False)
        for checkbox in (self.new_question_notifications,self.countdown_notifications,self.essay_sound):
            self.notification_box.addWidget(checkbox);checkbox.toggled.connect(self.save_notification_preferences)
        from .notification_popup import NewQuestionPopup
        self.new_question_popup=NewQuestionPopup()
        self.countdown_popup=NewQuestionPopup(bottom_offset=180)
        self.notification_test=QPushButton('测试新题提醒');self.notification_test.clicked.connect(self.test_new_question_notification)
        self.notification_box.addWidget(self.notification_test)
        self.countdown_test=QPushButton('测试倒计时提醒');self.countdown_test.clicked.connect(self.test_countdown_notification)
        self.notification_box.addWidget(self.countdown_test)
        self.essay_sound_test=QPushButton('测试主观题提示音');self.essay_sound_test.clicked.connect(self.play_essay_sound)
        self.notification_box.addWidget(self.essay_sound_test)
        self.new_question_notifications.toggled.connect(lambda checked:None if checked else self.new_question_popup.hide())
        self.countdown_notifications.toggled.connect(lambda checked:None if checked else self.countdown_popup.hide())
        self.status=QLabel('已停止');box.addWidget(self.status)
        link=QLabel(f'<a href="{self.server.url}/teacher">打开模拟教师页</a>');link.setOpenExternalLinks(True);box.addWidget(link)
        self.mode=QComboBox();self.mode.addItems(['人工审查（点击确认后仅模拟提交）',f"倒计时模式（仅模拟：剩余{self.config.get('timing',{}).get('threshold',10)}秒自动提交）",'自动模式（仅模拟：分析后自动提交）']);self.mode.currentIndexChanged.connect(self.change_mode);box.addWidget(self.mode)
        self.countdown_label=QLabel('剩余时间未知');box.addWidget(self.countdown_label)
        self.headless=QCheckBox('无头 Edge（需停止后切换）');self.headless.setChecked(self.config.get('browser',{}).get('headless',True));box.addWidget(self.headless)
        for title,func in [('启动监测',self.start),('暂停 / 恢复',self.pause),('停止',self.stop),('审查确认并提交到本地模拟课堂',self.review_submit),('重新分析当前已识别题',self.force_analysis),('历史与用量',self.show_history),('清除答案缓存、历史与用量',self.clear_history),('退出软件',self.quit)]:
            b=QPushButton(title);b.clicked.connect(func);box.addWidget(b)
        self.output=QTextEdit();self.output.setReadOnly(True);box.addWidget(self.output)
        self.tray=QSystemTrayIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon),self)
        menu=QMenu(self);menu.addAction('显示窗口',self.show);menu.addAction('退出软件',self.quit);self.tray.setContextMenu(menu);self.tray.show()
        self.tray.activated.connect(lambda reason:self.show() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None)
        from .real_panel import RealPanel
        profile=self.data/'real-student/rainclass-edge-profile'
        previous=base/'.local/teacher-adaptation/rainclass-edge-profile'
        if not getattr(sys,'frozen',False) and previous.is_dir():profile=previous
        self.real_panel=RealPanel(self.data/'real-readonly',profile,self)
        self.real_panel.ai_config=self.config.get('ai',{})
        self.real_panel.notify.connect(self.on_real_question)
        self.real_panel.time_alert.connect(self.on_real_alert)
        self.real_panel.update_config_summary()
        self.tabs.removeTab(0)
        self.tabs.addTab(self.real_panel,'真实课堂')
        self.tabs.addTab(self.real_panel.settings_page,'课堂设置')
        self.tabs.addTab(root,'本地模拟')
        self.real_panel.settings_requested.connect(lambda:self.tabs.setCurrentWidget(self.real_panel.settings_page))
        self.real_panel.monitor_requested.connect(lambda:self.tabs.setCurrentWidget(self.real_panel))
        for widget in (self.new_question_notifications,self.countdown_notifications,self.essay_sound,self.notification_test,self.countdown_test,self.essay_sound_test):
            self.notification_box.removeWidget(widget)
            self.real_panel.settings_forms['提醒与恢复'].addRow(widget)
        self.tabs.setCurrentWidget(self.real_panel)
    def start(self):
        if self.worker and self.worker.isRunning(): return
        self.worker=Worker(self.server.url,self.data/'rainclass-edge-profile',self.headless.isChecked(),max(.1,float(self.config.get('browser',{}).get('health_interval',.5))),{**self.config.get('ai',{}),'cloud_enabled':self.cloud.isChecked(),'persist':self.persist.isChecked(),'timing':self.config.get('timing',{})})
        self.change_mode()
        self.worker.countdown.connect(self.countdown_label.setText)
        self.worker.alert.connect(self.on_alert)
        self.worker.new_question.connect(self.on_new_question)
        self.worker.update.connect(self.on_status);self.worker.question.connect(self.on_question);self.worker.start()
    def change_mode(self,*args):
        if self.worker:self.worker.mode=('review','smart','auto')[self.mode.currentIndex()]
    def review_submit(self):
        if self.worker and self.worker.isRunning():self.worker.review_request.set()
    def on_alert(self,text):
        self.output.insertPlainText(text+'\n')
        if self.countdown_notifications.isChecked():self.show_countdown_notice('课堂时间提醒',text,'mock')
    def save_notification_preferences(self,*args):
        data={'new_question_notifications':self.new_question_notifications.isChecked(),'countdown_notifications':self.countdown_notifications.isChecked(),'essay_sound':self.essay_sound.isChecked()}
        try:
            temp=self.data/'ui-preferences.json.tmp'
            temp.write_text(json.dumps(data),encoding='utf-8');temp.replace(self.data/'ui-preferences.json')
        except OSError:
            self.status.setText('提醒设置本次已生效，但保存失败')
    def on_new_question(self,kind):
        if self.new_question_notifications.isChecked():
            self.show_new_question_notice('发现模拟新题',f'发现{kind}，请查看软件。','mock')
    def on_real_question(self,kind):
        if kind=='主观题' and self.essay_sound.isChecked():self.play_essay_sound()
        if self.new_question_notifications.isChecked():self.show_new_question_notice('发现真实课堂新题',f'发现{kind}，请查看原图并核对内容。','real')
    def play_essay_sound(self):
        # MessageBeep queues the Windows system sound and returns immediately.
        # It does not block classroom monitoring or require a bundled audio file.
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except (ImportError,RuntimeError):QApplication.beep()
    def show_new_question_notice(self,title,text,source):
        self.new_question_popup.show_notice(title,text)
        try:
            with (self.data/'notification-events.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps({'time_unix':time.time(),'event':'new_question_popup','source':source})+'\n')
        except OSError:pass
    def test_new_question_notification(self):
        self.notification_hint.setText('' if self.new_question_notifications.isChecked() else '新题提醒已关闭：请先勾选“新题弹窗提醒”，再点击测试。')
        self.notification_hint.setVisible(not self.new_question_notifications.isChecked())
        if self.new_question_notifications.isChecked():
            self.show_new_question_notice('新题提醒测试','新题提醒会以此方式显示，10 秒后自动关闭。','test')
        else:self.status.setText('请先开启新题弹窗提醒。')
    def on_real_alert(self,text):
        if self.countdown_notifications.isChecked():self.show_countdown_notice('真实课堂时间提醒',text,'real')
    def show_countdown_notice(self,title,text,source):
        self.countdown_popup.show_notice(title,text)
        try:
            with (self.data/'notification-events.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps({'time_unix':time.time(),'event':'countdown_popup','source':source})+'\n')
        except OSError:pass
    def test_countdown_notification(self):
        self.notification_hint.setText('' if self.countdown_notifications.isChecked() else '倒计时提醒已关闭：请先勾选“倒计时弹窗提醒”，再点击测试。')
        self.notification_hint.setVisible(not self.countdown_notifications.isChecked())
        if self.countdown_notifications.isChecked():
            self.show_countdown_notice('倒计时提醒测试','示例：距离作答结束还有 10 秒。此为显示测试。','test')
        else:self.status.setText('请先开启倒计时弹窗提醒。')
    def force_analysis(self):
        if self.worker and self.worker.isRunning():self.worker.reanalyze.set()
    def show_history(self):
        store=Store(self.data/'analysis.sqlite3')
        try:
            self.on_question('【云端用量统计】\n'+usage_text(store.summary()))
            for row in store.history():self.on_question(result_text(row))
        finally:store.close()
    def clear_history(self):
        if self.worker and self.worker.isRunning():
            self.output.append('请先停止监测后清除历史。');return
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self,'清除模拟缓存、历史与用量','确认删除本地模拟的答案缓存、历史和用量统计？不影响真实课堂记录及供应商账单。')!=QMessageBox.StandardButton.Yes:return
        store=Store(self.data/'analysis.sqlite3')
        try:store.clear(include_usage=True);self.output.clear()
        finally:store.close()
    def on_status(self,text):
        self.status.setText(text);logging.info(json.dumps({'event':'state','status':text},ensure_ascii=False))
    def on_question(self,text):
        self.output.moveCursor(QTextCursor.MoveOperation.End)
        self.output.insertPlainText(text+'\n\n')
    def pause(self):
        if self.worker:
            if self.worker.paused.is_set():self.worker.paused.clear()
            else:self.worker.paused.set();self.status.setText('已暂停');self.countdown_label.setText('已暂停，时间未同步')
    def stop(self):
        if self.worker:self.worker.stopping.set()
        self.status.setText('正在停止');self.countdown_label.setText('监测已停止，时间未同步')
    def closeEvent(self,event):
        if QSystemTrayIcon.isSystemTrayAvailable():event.ignore();self.hide()
        else:self.quit()
    def quit(self):
        self.stop()
        self.real_panel.stop()
        self.real_panel.close_analysis()
        if not self.real_panel.analysis_closed():QTimer.singleShot(100,self.quit);return
        # Avoid destroying a live Qt thread; poll without blocking the GUI.
        if self.worker and self.worker.isRunning(): QTimer.singleShot(100,self.quit);return
        if self.real_panel.is_running():QTimer.singleShot(100,self.quit);return
        self.new_question_popup.close();self.countdown_popup.close();self.server.close();self.tray.hide();QApplication.instance().quit()

def main():
    import argparse
    parser=argparse.ArgumentParser(description='RainClass Assistant 1.0.0')
    parser.add_argument('--smoke-test',action='store_true')
    parser.add_argument('--smoke-report',default='smoke-report.json')
    parser.add_argument('--data-dir')
    parser.add_argument('--ocr-self-test-report')
    parser.add_argument('--real-readonly',action='store_true',help='Open the real student tab; review, analysis and optional automatic answering')
    args=parser.parse_args()
    app=QApplication(sys.argv);app.setQuitOnLastWindowClosed(False)
    if args.ocr_self_test_report:
        from .ocr_smoke import run
        return run(app,args.ocr_self_test_report)
    try:w=Window(args.data_dir)
    except Exception as e:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None,'启动失败','请检查配置文件和数据目录权限。错误类型：'+type(e).__name__)
        return 1
    if args.smoke_test:
        from .smoke import SmokeRun
        smoke=SmokeRun(w,args.smoke_report)
        smoke.start()
    else:
        w.tabs.setCurrentWidget(w.real_panel)
        QTimer.singleShot(0,w.real_panel.start)
        w.show()
    return app.exec()
