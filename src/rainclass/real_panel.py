"""Real classroom preview and human correction UI. Reviewed analysis with optional real answer actions."""
from pathlib import Path
from threading import Event
from queue import Full
import json
import time
from PySide6.QtCore import Qt,Signal,QTimer,QSignalBlocker
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,
    QTextEdit,QComboBox,QSpinBox,QSplitter,QScrollArea,QFormLayout,QCheckBox,QTabWidget,QSizePolicy,QFrame,QMessageBox,QGridLayout,QDoubleSpinBox)
from .real_review import validate_draft
from .real_worker import RealWorker

LABELS={'WAITING_FOR_CLASS':'请在 Edge 中登录学生账号，并从课程列表进入课堂',
 'IGNORE_PPT':'普通 PPT，不产生新题提醒','ACTIVE_EXERCISE':'正在作答的正式习题',
 'CLOSED_EXERCISE':'题目已结束','NOT_VERIFIED':'页面或图片未就绪，暂不判定',
 'RECOVERING':'读取中断，等待恢复','FOLLOWING_EXERCISE':'发现新习题，正在切换并核对页面','PAUSED':'已暂停','STOPPED':'已停止'}
LABELS.update(DISCOVERING='正在检查课程',ENTERING_CLASS='正在进入课堂',LOGIN_REQUIRED='请正常扫码登录',COURSE_CHOICE_REQUIRED='多门课程正在进行，请选择课程')
LABELS.update(AUTO_ENTER_DISABLED='发现正在上课的课堂，自动进入已关闭')

class RealPanel(QWidget):
    settings_requested=Signal()
    monitor_requested=Signal()
    notify=Signal(str)
    time_alert=Signal(str)
    def __init__(self,data_dir,profile,parent=None):
        super().__init__(parent)
        self.data_dir=Path(data_dir);self.data_dir.mkdir(parents=True,exist_ok=True)
        self.worker=None;self.active_key=None;self.payload=None;self.confirmed=None;self.dirty=False;self.last_active_at=0
        self.review_status='NEEDS_REVIEW'
        self.auto_future=None;self.auto_snapshot=None;self.auto_seen=set()
        self.essay_permission=None;self.essay_denied=set()
        self.answer_valid=None
        self.ai_config={};self.analysis=None;self.analysis_future=None;self.analysis_snapshot=None;self.lesson_key=None;self.analysis_epoch=0
        self.original_image=QPixmap()
        box=QVBoxLayout(self);box.setContentsMargins(12,12,12,12);box.setSpacing(8)
        self.setStyleSheet("""
            RealPanel { background: #f4f6fa; }
            QFrame#classroomCard, QFrame#logCard, QFrame#settingsCard {
                background: white; border: 1px solid #dce2eb; border-radius: 6px;
            }
            QTextEdit, QLineEdit, QComboBox, QSpinBox {
                background: white; color: #172b45; border: 1px solid #cbd5e1;
                border-radius: 4px; padding: 4px; selection-background-color: #2563eb;
            }
            QPushButton { padding: 5px 10px; }
            QSplitter::handle { background: #e2e8f0; }
            QSplitter::handle:hover { background: #94b7e8; }
        """)
        title=QLabel('真实课堂监测');font=title.font();font.setPointSize(font.pointSize()+3);font.setBold(True);title.setFont(font)
        heading=QHBoxLayout();heading.addWidget(title);heading.addStretch()
        self.timer_label=QLabel('剩余时间未知');font=self.timer_label.font();font.setBold(True);self.timer_label.setFont(font)
        heading.addWidget(self.timer_label);box.addLayout(heading)
        note=QLabel('人工核对后点击 AI 分析 · 可自动填写并提交，请留意自动作答开关');note.setWordWrap(True);box.addWidget(note)
        row=QHBoxLayout();box.addLayout(row)
        self.start_button=QPushButton('启动真实学生端');self.start_button.clicked.connect(self.start)
        self.start_button.setStyleSheet('QPushButton {background:#2563eb;color:white;border:0;border-radius:4px;padding:6px 12px;}')
        self.pause_button=QPushButton('暂停 / 恢复');self.pause_button.clicked.connect(self.pause)
        self.stop_button=QPushButton('停止真实监测');self.stop_button.clicked.connect(self.stop)
        self.recover_button=QPushButton('恢复课堂');self.recover_button.clicked.connect(self.recover)
        for b in (self.start_button,self.pause_button,self.stop_button,self.recover_button):row.addWidget(b)
        row.addStretch()
        self.settings_button=QPushButton('课堂设置');self.settings_button.clicked.connect(self.settings_requested);row.addWidget(self.settings_button)
        self.settings_panel=QFrame();self.settings_panel.setObjectName('settingsCard');settings=QFormLayout(self.settings_panel)
        self.settings_area=QScrollArea();self.settings_area.setWidgetResizable(True);self.settings_area.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_area.setWidget(self.settings_panel)
        self.profile=QLineEdit(str(profile));settings.addRow('专用 Edge 登录资料目录',self.profile)
        self.profile.setToolTip('使用独立的 rainclass-edge-profile 目录；不要选择平时的 Edge 用户目录。')
        self.follow_new=QCheckBox('自动跟随新习题（关闭后可手动查看旧题）');self.follow_new.setChecked(True)
        self.follow_new.toggled.connect(self.set_follow);settings.addRow(self.follow_new)
        try:self.lifecycle_settings=json.loads((self.data_dir/'lifecycle-settings.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):self.lifecycle_settings={}
        self.auto_enter=QCheckBox('自动进入唯一正在上课的课程');self.auto_enter.setChecked(self.lifecycle_settings.get('auto_enter',True));settings.addRow(self.auto_enter)
        self.silent_recovery=QCheckBox('静默后台运行（关闭 Edge 后不显示恢复窗口）')
        self.silent_recovery.setChecked(self.lifecycle_settings.get('silent_recovery',False))
        self.silent_recovery.setToolTip('开启：关闭浏览器后在后台恢复；关闭：重新打开可见 Edge。更改在下次浏览器恢复时生效。')
        settings.addRow(self.silent_recovery);self.silent_recovery.toggled.connect(self.save_lifecycle)
        self.preferred=QLineEdit(self.lifecycle_settings.get('preferred',''));self.preferred.setPlaceholderText('多门课程同时上课时优先进入的完整课程名（可留空）');settings.addRow('优先课程',self.preferred)
        self.auto_enter.toggled.connect(self.save_lifecycle);self.preferred.textChanged.connect(self.save_lifecycle)
        self.refresh_limit=QSpinBox();self.refresh_limit.setRange(0,5)
        limit=self.lifecycle_settings.get('refresh_limit',2)
        self.refresh_limit.setValue(limit if type(limit) is int and 0<=limit<=5 else 2)
        self.refresh_limit.setToolTip('每个新题目标的最大自动刷新次数，0 表示不自动刷新；仍受总恢复时间上限约束。')
        settings.addRow('新题恢复最多刷新次数',self.refresh_limit)
        self.refresh_limit.valueChanged.connect(self.save_lifecycle)
        self.state_label=QLabel('已停止');self.state_label.setWordWrap(True)
        self.state_label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);box.addWidget(self.state_label)
        self.content_splitter=QSplitter(Qt.Orientation.Vertical);self.content_splitter.setChildrenCollapsible(False);box.addWidget(self.content_splitter,1)
        splitter=QSplitter(Qt.Orientation.Horizontal);self.question_splitter=splitter;splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(splitter)
        image_side=QFrame();image_side.setObjectName('classroomCard');image_side.setMinimumWidth(0);il=QVBoxLayout(image_side)
        il.addWidget(QLabel('题目原图 · 仅保留在本次会话内存中'))
        area=QScrollArea();self.image_area=area;area.setWidgetResizable(True);area.setMinimumSize(0,0)
        self.image=QLabel('等待真实课堂题目');self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
        area.setWidget(self.image);il.addWidget(area,1)
        self.fit_image=QCheckBox('缩放适合窗口（取消可查看原始大小）');self.fit_image.setChecked(True)
        self.fit_image.toggled.connect(self.render_image);il.addWidget(self.fit_image)
        self.refresh_button=QPushButton('重新读取图片与 OCR');self.refresh_button.clicked.connect(self.refresh_image);il.addWidget(self.refresh_button)
        splitter.addWidget(image_side)
        editor=QFrame();editor.setObjectName('classroomCard');editor.setMinimumWidth(0);form=QVBoxLayout(editor)
        self.review_tabs=QTabWidget();form.addWidget(self.review_tabs,1)
        review=QWidget();fields=QVBoxLayout(review);fields.setContentsMargins(6,6,6,6)
        meta=QHBoxLayout();fields.addLayout(meta);meta.addWidget(QLabel('题型'))
        self.kind=QComboBox()
        for label,value in [('请选择并核对题型','UNKNOWN'),('单选题','single'),('多选题','multiple'),('填空题','blank'),('主观题 / 简答题','essay')]:self.kind.addItem(label,value)
        meta.addWidget(self.kind,1)
        self.blanks=QSpinBox();self.blanks.setRange(0,50);self.blanks.setSpecialValueText('待核对');self.blanks.setToolTip('当前整页填空总数，不是题目数量；无法识别时请手动填写。');meta.addWidget(QLabel('空数（仅填空题）'));meta.addWidget(self.blanks)
        self.field_splitter=QSplitter(Qt.Orientation.Vertical);self.field_splitter.setChildrenCollapsible(False);fields.addWidget(self.field_splitter,1)
        stem_side=QWidget();sl=QVBoxLayout(stem_side);sl.setContentsMargins(0,0,0,0);sl.addWidget(QLabel('题干'))
        self.stem=QTextEdit();self.stem.setPlaceholderText('对照原图核对题干，移除 OCR 中混入的标题、选项和倒计时');sl.addWidget(self.stem,1)
        option_side=QWidget();ol=QVBoxLayout(option_side);ol.setContentsMargins(0,0,0,0);ol.addWidget(QLabel('选项'))
        self.options=QTextEdit();self.options.setPlaceholderText('选择题每行一个选项，按 A、B、C…顺序填写');ol.addWidget(self.options,1)
        for text in (self.stem,self.options):
            text.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Ignored);text.setMinimumHeight(48)
        self.field_splitter.addWidget(stem_side);self.field_splitter.addWidget(option_side);self.field_splitter.setSizes([200,200])
        self.review_tabs.addTab(review,'题目核对')
        raw=QWidget();rl=QVBoxLayout(raw)
        raw_note=QLabel('识别原文仅供核对，可选中复制；题干与选项请在“题目核对”中修改。');raw_note.setWordWrap(True);rl.addWidget(raw_note)
        self.ocr=QTextEdit();self.ocr.setReadOnly(True);rl.addWidget(self.ocr,1)
        copy=QPushButton('填入识别的题干与选项（仍需核对）');copy.clicked.connect(self.copy_ocr);rl.addWidget(copy)
        self.review_tabs.addTab(raw,'OCR 原文')
        self.review_label=QLabel('请先取得当前题目的原图');self.review_label.setWordWrap(True)
        self.review_label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);form.addWidget(self.review_label)
        self.confirm_button=QPushButton('确认核对（暂不调用 AI）');self.confirm_button.clicked.connect(self.confirm);analysis_actions=QHBoxLayout();form.addLayout(analysis_actions);analysis_actions.addWidget(self.confirm_button)
        self.ai_enabled=QCheckBox('启用真实 AI（按所选模式发送核对文本或题图）');settings.addRow(self.ai_enabled);self.ai_enabled.toggled.connect(self.cancel_answer)
        self.essay_mode=QComboBox();self.essay_mode.addItem('每题由我核对并决定是否允许 AI','review');self.essay_mode.addItem('AI 自动核对、填写并提交','auto');settings.addRow('主观题处理',self.essay_mode)
        self.essay_auto_submit=QCheckBox('主观题自动模式：填写后也提交');self.essay_auto_submit.setChecked(True);settings.addRow(self.essay_auto_submit)
        self.essay_mode.currentIndexChanged.connect(self.clear_analysis_display);self.essay_auto_submit.toggled.connect(self.cancel_answer)
        self.run_mode=QComboBox();self.run_mode.addItem('手动核对 → 点击分析','manual');self.run_mode.addItem('AI 对照原图自动核对 → 分析 → 填写提交','auto');settings.addRow('运行模式',self.run_mode)
        self.run_mode.currentIndexChanged.connect(self.auto_mode_changed)
        vision_note=QLabel('自动模式会将当前题图和 OCR 文本发送至配置的模型；视觉核对和解题分别计入请求/预算。无法核对转人工。');vision_note.setWordWrap(True);settings.addRow(vision_note)
        self.auto_answer=QCheckBox('启用自动作答（填写和提交按题型策略执行）');self.auto_answer.setChecked(True);settings.addRow(self.auto_answer)
        self.auto_answer.toggled.connect(self.cancel_answer)
        self.answer_label=QLabel('自动填写和提交已启用（仅当前已核对并点击分析的题目）');self.answer_label.setWordWrap(True);form.addWidget(self.answer_label)
        self.ai_persist=QCheckBox('保存本地结果缓存与历史（关闭仍保留预算所需用量）');self.ai_persist.setChecked(True);settings.addRow(self.ai_persist)
        self.ai_button=QPushButton('AI 分析当前题目');self.ai_button.clicked.connect(self.analyze_current);analysis_actions.addWidget(self.ai_button)
        self.essay_actions=QWidget();essay_row=QHBoxLayout(self.essay_actions);essay_row.setContentsMargins(0,0,0,0)
        self.essay_allow=QPushButton('允许 AI 填写并提交本题');self.essay_deny=QPushButton('不用 AI，我手动答');essay_row.addWidget(self.essay_allow);essay_row.addWidget(self.essay_deny);form.addWidget(self.essay_actions);self.essay_actions.hide()
        self.essay_allow.clicked.connect(self.allow_essay);self.essay_deny.clicked.connect(self.deny_essay)
        self.kind.currentIndexChanged.connect(lambda:self.essay_actions.setVisible(self.kind.currentData()=='essay'))
        self.ai_output=QTextEdit();self.ai_output.setReadOnly(True);self.review_tabs.addTab(self.ai_output,'AI 参考分析')
        self.ai_history=QTextEdit();self.ai_history.setReadOnly(True);self.review_tabs.addTab(self.ai_history,'真实历史 / 用量')
        self.refresh_ai_history=QPushButton('查看真实历史与用量');settings.addRow(self.refresh_ai_history);self.refresh_ai_history.clicked.connect(self.refresh_analysis_history)
        self.clear_ai_history=QPushButton('清除真实缓存、历史与用量');settings.addRow(self.clear_ai_history);self.clear_ai_history.clicked.connect(self.clear_analysis_history)
        self.ai_timer=QTimer(self);self.ai_timer.setInterval(100);self.ai_timer.timeout.connect(self.poll_analysis);self.ai_timer.start()
        splitter.addWidget(editor);splitter.setSizes([520,600]);splitter.setStretchFactor(0,1);splitter.setStretchFactor(1,1)
        logs=QFrame();logs.setObjectName('logCard');ll=QVBoxLayout(logs);log_row=QHBoxLayout();log_row.addWidget(QLabel('运行日志'));log_row.addStretch()
        self.clear_log_button=QPushButton('清除日志');log_row.addWidget(self.clear_log_button);ll.addLayout(log_row)
        self.log=QTextEdit();self.log.setReadOnly(True)
        self.log.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Ignored);self.log.setMinimumHeight(48);ll.addWidget(self.log,1)
        self.clear_log_button.setToolTip('仅清空下方显示，不删除诊断文件或题目去重记录。')
        self.clear_log_button.clicked.connect(self.log.clear)
        self.content_splitter.addWidget(logs);self.content_splitter.setSizes([520,240]);self.content_splitter.setStretchFactor(0,3);self.content_splitter.setStretchFactor(1,1)
        splitter.splitterMoved.connect(self.render_image);self.content_splitter.splitterMoved.connect(self.render_image)
        for signal in (self.kind.currentIndexChanged,self.stem.textChanged,self.options.textChanged,self.blanks.valueChanged):signal.connect(self.edited)
        self.confirm_button.setEnabled(False)
        self.build_settings_page(settings,vision_note)
        self.restore_preferences()

    def restore_preferences(self):
        self.preference_checks=('follow_new','fit_image','ai_enabled','auto_answer','essay_auto_submit','ai_persist')
        self.preference_modes=('run_mode','essay_mode')
        try:
            saved=json.loads((self.data_dir/'classroom-preferences.json').read_text(encoding='utf-8'))
            if not isinstance(saved,dict):saved={}
        except (OSError,ValueError):saved={}
        # Block dependent mode callbacks while restoring the exact saved combination.
        blockers=[QSignalBlocker(getattr(self,name)) for name in (*self.preference_checks,*self.preference_modes,'profile')]
        for name in self.preference_checks:
            if type(saved.get(name)) is bool:getattr(self,name).setChecked(saved[name])
        for name in self.preference_modes:
            widget=getattr(self,name);index=widget.findData(saved.get(name))
            if index>=0:widget.setCurrentIndex(index)
        if isinstance(saved.get('profile'),str) and saved['profile'].strip():self.profile.setText(saved['profile'])
        del blockers
        for name in self.preference_checks:getattr(self,name).toggled.connect(self.save_preferences)
        for name in self.preference_modes:getattr(self,name).currentIndexChanged.connect(self.save_preferences)
        self.profile.textChanged.connect(self.save_preferences)
        self.cancel_answer()

    def save_preferences(self,*args):
        saved={name:getattr(self,name).isChecked() for name in self.preference_checks}
        saved.update({name:getattr(self,name).currentData() for name in self.preference_modes})
        saved['profile']=self.profile.text()
        try:
            path=self.data_dir/'classroom-preferences.json';temp=path.with_suffix('.tmp')
            temp.write_text(json.dumps(saved,ensure_ascii=False),encoding='utf-8');temp.replace(path)
        except OSError:self.log.insertPlainText('课堂设置保存失败，下次启动可能无法恢复。\n')

    def build_settings_page(self,old_form,vision_note):
        self.settings_page=QWidget(self);self.settings_page.setObjectName('classroomSettings');self.settings_page.hide()
        layout=QVBoxLayout(self.settings_page);layout.setContentsMargins(18,16,18,16);layout.setSpacing(12)
        title=QLabel('课堂设置');font=title.font();font.setPointSize(font.pointSize()+6);font.setBold(True);title.setFont(font);layout.addWidget(title)
        hint=QLabel('设置更改后自动保存，重启继续使用；切换页面不影响当前监测。');hint.setWordWrap(True);layout.addWidget(hint)
        old_panel=self.settings_area.takeWidget()
        self.settings_panel=QWidget();grid=QGridLayout(self.settings_panel);grid.setContentsMargins(0,0,0,0);grid.setSpacing(14)
        self.settings_forms={}
        for index,name in enumerate(('作答策略','AI 与用量','课堂连接','提醒与恢复')):
            card=QFrame();card.setObjectName('settingsCard');card.setMinimumWidth(0)
            card_box=QVBoxLayout(card);card_box.setContentsMargins(16,16,16,16)
            heading=QLabel(name);f=heading.font();f.setBold(True);f.setPointSize(f.pointSize()+2);heading.setFont(f);card_box.addWidget(heading)
            form=QFormLayout();form.setSpacing(12);form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows);card_box.addLayout(form);card_box.addStretch()
            self.settings_forms[name]=form;grid.addWidget(card,index//2,index%2)
        strategy=(self.run_mode,self.essay_mode,self.essay_auto_submit,self.auto_answer,vision_note)
        ai=(self.ai_enabled,self.ai_persist,self.refresh_ai_history,self.clear_ai_history)
        reminders=(self.refresh_limit,self.silent_recovery)
        while old_form.rowCount():
            taken=old_form.takeRow(0)
            field=taken.fieldItem.widget();label=taken.labelItem.widget() if taken.labelItem else None
            name='作答策略' if field in strategy else 'AI 与用量' if field in ai else '提醒与恢复' if field in reminders else '课堂连接'
            if label:
                label.setWordWrap(False)
                if field is self.run_mode:label.setText('选择题 / 填空题')
                self.settings_forms[name].addRow(label,field)
            else:self.settings_forms[name].addRow(field)
            if isinstance(field,QComboBox):
                field.setMinimumContentsLength(12);field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                field.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        old_panel.deleteLater()
        self.settings_forms['AI 与用量'].setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.model_info=QLabel('尚未配置')
        self.budget_info=QDoubleSpinBox();self.budget_info.setRange(.1,10.0);self.budget_info.setDecimals(1);self.budget_info.setSingleStep(.1);self.budget_info.setKeyboardTracking(False);self.budget_info.setSuffix(' 元')
        saved={}
        try:
            saved=json.loads((self.data_dir/'real-ai-limits.json').read_text(encoding='utf-8'))
            value=saved.get('budget',.5)
            if type(value) not in (int,float) or not .1<=value<=10:value=.5
        except (OSError,ValueError,AttributeError):value=.5
        self.budget_enabled=QCheckBox('启用单课预算上限（关闭后金额无上限）')
        self.budget_enabled.setChecked(not isinstance(saved,dict) or saved.get('enabled',True) is not False)
        self.budget_info.setValue(value);self.budget_info.setEnabled(self.budget_enabled.isChecked())
        self.budget_info.valueChanged.connect(self.save_budget);self.budget_enabled.toggled.connect(self.save_budget)
        self.settings_forms['AI 与用量'].addRow(self.budget_enabled)
        self.budget_notice=QLabel('按保守预留金额控制请求；不等于平台实际扣费。已有请求记录不会清零，降低上限可能立即阻止后续请求。调整后会重查仅因预算暂停的题目，可能产生新请求。');self.budget_notice.setWordWrap(True)
        for label,widget in (('配置模型',self.model_info),('单课预算上限（人民币）',self.budget_info)):
            if isinstance(widget,QLabel):widget.setWordWrap(True);widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.settings_forms['AI 与用量'].addRow(label,widget)
        self.settings_forms['AI 与用量'].addRow(self.budget_notice)
        grid.setColumnStretch(0,1);grid.setColumnStretch(1,1)
        self.settings_area.setWidget(self.settings_panel);layout.addWidget(self.settings_area,1)
        self.settings_back=QPushButton('返回真实课堂');self.settings_back.clicked.connect(self.monitor_requested);layout.addWidget(self.settings_back,alignment=Qt.AlignmentFlag.AlignLeft)
        self.settings_page.setStyleSheet(self.styleSheet()+' QWidget#classroomSettings {background:#f4f6fa;} QCheckBox {spacing:7px;}')

    def update_config_summary(self):
        profiles=self.ai_config.get('profiles',[])
        self.model_info.setText(' / '.join(str(p.get('model','未知')) for p in profiles[:2]) or '尚未配置')
        self.apply_budget()

    def apply_budget(self):
        budget=self.budget_info.value() if self.budget_enabled.isChecked() else None
        self.budget_info.setEnabled(self.budget_enabled.isChecked())
        self.ai_config={**self.ai_config,'budget':budget,'call_limit':None}
        if self.analysis and not self.analysis.closing:
            for key in self.analysis.set_budget(budget):self.auto_seen.discard(key)

    def save_budget(self,*args):
        self.apply_budget()
        try:
            path=self.data_dir/'real-ai-limits.json';temp=path.with_suffix('.tmp')
            temp.write_text(json.dumps({'budget':self.budget_info.value(),'enabled':self.budget_enabled.isChecked(),'currency':'CNY'}),encoding='utf-8');temp.replace(path)
        except OSError:self.budget_notice.setText('预算已在本次运行生效，但保存失败，下次启动请检查。')

    def start(self):
        if self.worker and self.worker.isRunning():return
        profile=Path(self.profile.text()).expanduser().resolve()
        if profile.name!='rainclass-edge-profile':
            self.log.insertPlainText('请使用名称为 rainclass-edge-profile 的专用资料目录。\n');return
        self.worker=RealWorker(profile,self.data_dir)
        self.save_lifecycle()
        self.set_follow(self.follow_new.isChecked())
        self.worker.answer_status.connect(self.on_answer_status)
        self.worker.status.connect(self.on_state);self.worker.preview.connect(self.on_preview)
        self.worker.notice.connect(lambda text:self.log.insertPlainText(text+'\n'))
        self.worker.new_question.connect(self.notify);self.worker.alert.connect(self.time_alert)
        self.worker.finished.connect(lambda:self.profile.setEnabled(True))
        self.profile.setEnabled(False);self.worker.start()

    def set_follow(self,enabled):
        if self.worker:
            if enabled:self.worker.follow_enabled.set()
            else:self.worker.follow_enabled.clear()

    def save_lifecycle(self,*args):
        settings={'auto_enter':self.auto_enter.isChecked(),'preferred':self.preferred.text().strip(),'silent_recovery':self.silent_recovery.isChecked(),'refresh_limit':self.refresh_limit.value()}
        (self.data_dir/'lifecycle-settings.json').write_text(json.dumps(settings,ensure_ascii=False),encoding='utf-8')
        if self.worker:
            self.worker.refresh_limit=settings['refresh_limit']
            if settings['silent_recovery']:self.worker.silent_recovery.set()
            else:self.worker.silent_recovery.clear()
            self.worker.preferred_course=settings['preferred']
            if settings['auto_enter']:self.worker.auto_enter.set()
            else:self.worker.auto_enter.clear()

    def on_state(self,state):
        if self.worker and (self.worker.stopping.is_set() or self.worker.paused.is_set()):
            state={'state':'STOPPED' if self.worker.stopping.is_set() else 'PAUSED','instance_key':None}
        key=state.get('instance_key')
        self.lesson_key=state.get('lesson_key') if key else None
        self.last_active_at=time.monotonic() if key else 0
        if key!=self.active_key:
            self.clear_analysis_display()
            self.review_status='NEEDS_REVIEW'
            self.active_key=key;self.confirmed=None
            self.review_label.setText('当前题目已变化或暂不可用，请重新核对。')
        self.state_label.setText(LABELS.get(state['state'],state['state'])+f" · 新题 {state.get('events',0)} · AI 请求 {self.request_count()} · 提交 {state.get('submissions',0)}")
        if state.get('login_state'):
            login={'SIGNED_IN':'已登录','LOGIN_REQUIRED':'需要重新登录','NOT_VERIFIED':'登录状态待确认'}.get(state['login_state'],state['login_state'])
            checked=state.get('last_query_at')
            checked_text=time.strftime('%H:%M:%S',time.localtime(checked)) if checked else '尚未查询'
            self.state_label.setText(self.state_label.text()+f" · {login} · 正在上课 {state.get('active_count',0)} 门 · 最近查询 {checked_text}")
        seconds=state.get('remaining_seconds')
        self.timer_label.setText(f'剩余 {seconds//60:02d}:{seconds%60:02d}' if seconds is not None else '剩余时间未知 / 题目不可作答')
        self._enable_confirm()

    def _enable_confirm(self):
        self.confirm_button.setEnabled(bool(self.payload and self.active_key and self.payload['instance_key']==self.active_key))

    def on_preview(self,payload):
        if payload['instance_key']!=self.active_key:return
        # Delayed OCR from a previous capture must not replace a newer image/draft.
        if not payload['ocr_pending'] and (not self.payload or payload['revision']!=self.payload['revision']):return
        fresh=not self.payload or payload['revision']!=self.payload['revision']
        if fresh:
            self.clear_analysis_display()
            self.confirmed=None;self.dirty=False;self.payload=payload
            self.stem.clear();self.options.clear();self.blanks.setValue(0)
            self.kind.setCurrentIndex(max(0,self.kind.findData(payload.get('question_type','UNKNOWN'))))
            pixmap=QPixmap();pixmap.loadFromData(payload['image'])
            self.original_image=pixmap;self.render_image()
            self.dirty=False
        else:self.payload=payload
        self.ocr.setPlainText('正在本机识别…' if payload['ocr_pending'] else payload.get('ocr_text',''))
        if not fresh and not self.dirty and self.kind.currentData()=='UNKNOWN':
            self.kind.setCurrentIndex(max(0,self.kind.findData(payload.get('type_hint','UNKNOWN'))))
            self.dirty=False
        if not payload['ocr_pending'] and not self.dirty:self._fill_candidate()
        candidate=payload.get('candidate',{})
        self.review_status='NEEDS_REVIEW'
        warning='；'.join(candidate.get('warnings',[]))
        self.review_label.setText('NEEDS_REVIEW · 待人工核对（含公式、符号及图片内容）。'+(candidate.get('source','')+'。' if candidate else '')+(warning or '请对照原图核对题型、题干、选项和空数。确认只保留本次内存草稿。'))
        self._enable_confirm()

    def edited(self,*args):
        self.clear_analysis_display()
        self.review_status='NEEDS_REVIEW'
        self.dirty=True;self.confirmed=None
        self.review_label.setText('内容已修改，请核对后重新确认。')

    def render_image(self,*args):
        if self.original_image.isNull():return
        pixmap=self.original_image
        if self.fit_image.isChecked():
            bounds=self.image_area.viewport().size()
            bounds.setWidth(max(1,bounds.width()-4));bounds.setHeight(max(1,bounds.height()-4))
            pixmap=pixmap.scaled(pixmap.size().boundedTo(bounds),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
            self.image.setMinimumSize(0,0)
        else:self.image.setMinimumSize(pixmap.size())
        self.image.setPixmap(pixmap)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'fit_image'):self.render_image()

    def copy_ocr(self):
        if self.stem.toPlainText().strip() or self.options.toPlainText().strip():
            self.review_label.setText('已有内容，请手动整理，避免覆盖核对结果。');return
        self._fill_candidate()

    def _fill_candidate(self):
        if not self.payload or self.payload['instance_key']!=self.active_key:return
        candidate=self.payload.get('candidate')
        if not candidate:return
        self.stem.blockSignals(True);self.options.blockSignals(True);self.blanks.blockSignals(True)
        try:
            self.stem.setPlainText(candidate.get('stem',''))
            self.options.setPlainText('\n'.join(o['label']+'. '+o['text'] for o in candidate.get('options',[])))
            if self.kind.currentData()=='blank':
                count=candidate.get('blank_count')
                self.blanks.setValue(count if type(count) is int and 1<=count<=50 else 0)
        finally:self.stem.blockSignals(False);self.options.blockSignals(False);self.blanks.blockSignals(False)
        self.confirmed=None

    def confirm(self):
        if not self.payload or self.active_key!=self.payload['instance_key']:
            self.review_label.setText('当前题目已失效，请等待新图。');return
        if time.monotonic()-self.last_active_at>3:
            self.review_label.setText('课堂状态未及时同步，请等待监测恢复后再确认。');return
        try:
            draft=validate_draft(self.active_key,self.payload['revision'],self.kind.currentData(),self.stem.toPlainText(),self.options.toPlainText(),self.blanks.value())
        except ValueError as error:self.review_label.setText(str(error));return
        self.confirmed=draft
        self.review_status='REVIEWED'
        self.review_label.setText('已确认核对，草稿仅保留在内存中。可另行点击 AI 分析；是否自动填写提交由课堂设置中的开关决定。')

    def refresh_image(self):
        if self.worker and self.worker.isRunning():
            self.clear_analysis_display();self.confirmed=None;self.worker.capture_request.set()

    def recover(self):
        if self.worker and self.worker.isRunning():
            self.invalidate();self.worker.recover_request.set()

    def invalidate(self):
        self.clear_analysis_display()
        self.review_status='NEEDS_REVIEW'
        self.active_key=None;self.confirmed=None;self._enable_confirm()

    def pause(self):
        if self.worker and self.worker.isRunning():
            self.invalidate()
            if self.worker.paused.is_set():self.worker.paused.clear()
            else:self.worker.paused.set()

    def stop(self):
        self.invalidate()
        if self.worker:self.worker.stopping.set()

    def is_running(self):return bool(self.worker and self.worker.isRunning())

    def clear_analysis_display(self,*args):
        self.essay_permission=None
        self.cancel_answer()
        self.analysis_epoch+=1
        if hasattr(self,'ai_output'):self.ai_output.clear()

    def analysis_ready(self):
        d=self.confirmed
        return bool(d and self.review_status=='REVIEWED' and self.payload and
                    d.instance_key==self.active_key and d.image_revision==self.payload['revision'] and
                    time.monotonic()-self.last_active_at<=3 and self.lesson_key)

    def analyze_current(self):
        if self.kind.currentData()=='essay' and self.essay_mode.currentData()=='review' and self.essay_permission!=(self.active_key,self.payload['revision'] if self.payload else None,self.analysis_epoch):
            self.ai_output.setPlainText('主观题请先核对并确认，再选择允许 AI 或手动作答。');return
        if not self.ai_enabled.isChecked():
            self.ai_output.setPlainText('请先勾选启用真实 AI。');return
        if not self.analysis_ready():
            self.ai_output.setPlainText('请等待当前课堂状态同步，并先确认核对。');return
        try:
            from .real_analysis import RealAnalysis,question
            question(self.confirmed,self.lesson_key)
            if self.analysis is None:
                self.analysis=RealAnalysis(self.data_dir/'analysis.sqlite3',self.ai_config,self.ai_persist.isChecked())
            if any(not f.done() for f in self.analysis.requests.values()):
                self.ai_output.setPlainText('已有分析请求进行中，请等待完成。');return
            self.analysis.service.persist=self.ai_persist.isChecked()
            future=self.analysis.submit(self.confirmed,self.lesson_key)
        except (ValueError, OSError) as error:
            self.ai_output.setPlainText(str(error));return
        self.cancel_answer()
        self.answer_valid=Event()
        if self.auto_answer.isChecked():self.answer_valid.set()
        self.analysis_future=future
        self.analysis_snapshot=(self.confirmed,self.lesson_key,self.analysis_epoch)
        self.ai_output.setPlainText('分析中；相同内容重复点击不会重新发送。失败或未知结果也不会自动重新发送。')
        self.review_tabs.setCurrentWidget(self.ai_output)

    def request_count(self):
        if not self.analysis or self.analysis.closing:return 0
        return sum(r['requests'] for r in self.analysis.store.summary())

    def poll_analysis(self):
        self.poll_auto()
        busy=bool((self.analysis_future and not self.analysis_future.done()) or (self.auto_future and not self.auto_future.done()))
        self.ai_button.setEnabled(not busy)
        if not self.analysis_future or not self.analysis_future.done():return
        future=self.analysis_future;self.analysis_future=None
        current=self.analysis_ready() and self.analysis_snapshot==(self.confirmed,self.lesson_key,self.analysis_epoch)
        try:
            result=future.result()
            if current:
                from .presentation import result_text
                self.ai_output.setPlainText(result_text(result))
                if self.auto_answer.isChecked() and self.answer_valid and self.answer_valid.is_set():
                    if self.worker and self.worker.isRunning():
                        try:
                            self.worker.answer_queue.put_nowait((self.confirmed,result,self.answer_valid,self.essay_should_submit(self.confirmed.kind)))
                            self.answer_label.setText('正在核实当前题目并自动填写'+('、提交…' if self.essay_should_submit(self.confirmed.kind) else '（不提交）…'))
                        except Full:self.answer_label.setText('已有作答任务等待处理，本次未执行。')
                    else:self.answer_label.setText('监测未运行，未自动填写或提交。')
        except Exception:
            if current:self.ai_output.setPlainText('分析失败或结果未知。请检查配置、网络或预算；为避免重复计费，相同内容本次会话不会自动重发。')
        if self.analysis and not self.analysis.closing:
            from .presentation import result_text,usage_text
            store=self.analysis.store
            self.ai_history.setPlainText('历史记录（可能来自旧题，仅供参考）\n'+usage_text(store.summary())+'\n费用单位以配置供应商为准；未配置价格时费用未知。\n\n'+'\n\n'.join(result_text(r) for r in store.history()))

    def close_analysis(self):
        if self.analysis:self.analysis.close()

    def analysis_closed(self):
        return not self.analysis or self.analysis.closed.is_set()

    def clear_analysis_history(self):
        from .storage import Store
        if self.analysis and self.analysis.closing:return
        if self.analysis and any(not f.done() for f in self.analysis.requests.values()):
            self.ai_output.setPlainText('请等待分析完成后再清除历史。');return
        if QMessageBox.question(self,'清除缓存、历史与用量','确认删除真实题目缓存、历史和本地用量统计？本地预算与请求次数计数将重置，不影响供应商账单。已提交题目记录保留。')!=QMessageBox.StandardButton.Yes:return
        # Invalidate completed callbacks before deleting results. Keep instance-level
        # futures and auto_seen so clearing accounting cannot trigger paid retries.
        self.clear_analysis_display();self.analysis_future=None;self.auto_future=None
        store=self.analysis.store if self.analysis else Store(self.data_dir/'analysis.sqlite3')
        try:store.clear(include_usage=True)
        finally:
            if not self.analysis:store.close()
        self.ai_history.setPlainText('真实缓存、历史与本地用量已清除。')
        self.log.insertPlainText('已清除真实缓存、历史与用量；已提交题目记录保留。\n')

    def refresh_analysis_history(self):
        from .storage import Store
        from .presentation import result_text,usage_text
        if self.analysis and self.analysis.closing:return
        path=self.data_dir/'analysis.sqlite3'
        if not path.exists():
            self.ai_history.setPlainText('暂无真实 AI 请求记录。');return
        store=self.analysis.store if self.analysis else Store(path)
        try:
            self.ai_history.setPlainText('历史记录（可能来自旧题，仅供参考）\n'+usage_text(store.summary())+'\n费用单位以配置供应商为准；未配置价格时费用未知。\n\n'+'\n\n'.join(result_text(r) for r in store.history()))
        finally:
            if not self.analysis:store.close()
        self.review_tabs.setCurrentWidget(self.ai_history)

    def cancel_answer(self,*args):
        if self.answer_valid:self.answer_valid.clear()
        if hasattr(self,'answer_label'):
            self.answer_label.setText('自动作答：'+('已启用；等待已核对题目的 AI 分析' if self.auto_answer.isChecked() else '已关闭'))

    def on_answer_status(self,message):
        self.answer_label.setText(message)
        self.log.insertPlainText(message+'\n')

    def auto_mode_changed(self,*args):
        self.clear_analysis_display()
        if self.run_mode.currentData()=='auto':self.auto_answer.setChecked(True)

    def poll_auto(self):
        if self.auto_future:
            if not self.auto_future.done():return
            future=self.auto_future;self.auto_future=None
            current=bool(self.payload and self.auto_snapshot==(self.active_key,self.payload['revision'],self.lesson_key,self.analysis_epoch) and self.answer_valid and self.answer_valid.is_set())
            try:
                draft,result=future.result()
                if not current:return
                for widget in (self.kind,self.stem,self.options,self.blanks):widget.blockSignals(True)
                try:
                    self.kind.setCurrentIndex(self.kind.findData(draft.kind));self.stem.setPlainText(draft.stem)
                    self.options.setPlainText('\n'.join(draft.options));self.blanks.setValue(draft.blank_count)
                finally:
                    for widget in (self.kind,self.stem,self.options,self.blanks):widget.blockSignals(False)
                self.confirmed=draft;self.review_status='AI_REVIEWED'
                self.review_label.setText('已由 AI 对照原图核对（非人工核对），请留意参考答案及提交回执。')
                from .presentation import result_text
                self.ai_output.setPlainText(result_text(result));self.review_tabs.setCurrentWidget(self.ai_output)
                if self.auto_answer.isChecked() and self.worker and self.worker.isRunning():
                    self.worker.answer_queue.put_nowait((draft,result,self.answer_valid,self.essay_should_submit(draft.kind)))
                    self.answer_label.setText('AI 核对与分析完成，正在填写'+('并提交…' if self.essay_should_submit(draft.kind) else '（不提交）…'))
            except Exception as error:
                if current:
                    from .analysis_errors import public_error
                    self.review_status='NEEDS_REVIEW'
                    self.ai_output.setPlainText('自动流程已停止：'+public_error(error)+'；本次不自动重试或提交。')
                    self.answer_label.setText('自动流程已停止，请人工核对。')
            return
        is_essay=bool(self.payload and self.payload.get('question_type')=='essay')
        if is_essay:
            if self.essay_mode.currentData()!='auto':return
        elif self.run_mode.currentData()!='auto':return
        if not self.ai_enabled.isChecked() or not self.auto_answer.isChecked():return
        if self.analysis_future or not self.worker or not self.worker.isRunning():return
        p=self.payload
        if not p or p.get('ocr_pending',True) or self.dirty or not self.active_key or not self.lesson_key or p['instance_key']!=self.active_key or time.monotonic()-self.last_active_at>3:return
        if self.active_key in self.essay_denied:return
        import hashlib
        key=(self.active_key,hashlib.sha256(p['image']).hexdigest())
        if key in self.auto_seen:return
        if self.analysis and any(not f.done() for f in self.analysis.requests.values()):return
        self.auto_seen.add(key)
        try:
            from .real_analysis import RealAnalysis
            if self.analysis is None:self.analysis=RealAnalysis(self.data_dir/'analysis.sqlite3',self.ai_config,self.ai_persist.isChecked())
            self.analysis.service.persist=self.ai_persist.isChecked()
            self.cancel_answer();self.answer_valid=Event();self.answer_valid.set()
            self.auto_snapshot=(self.active_key,p['revision'],self.lesson_key,self.analysis_epoch)
            self.auto_future=self.analysis.submit_auto(p,self.lesson_key,self.answer_valid)
            self.ai_output.setPlainText('自动模式：正在对照原图核对 OCR，成功后继续解题并填写提交。')
            self.answer_label.setText('AI 原图核对进行中…')
        except (ValueError,OSError):
            self.answer_label.setText('自动模式配置不可用，请检查模型、Key 和预算；本题请人工处理。')

    def essay_should_submit(self,kind):
        return kind!='essay' or self.essay_mode.currentData()=='review' or self.essay_auto_submit.isChecked()

    def allow_essay(self):
        if self.kind.currentData()!='essay':return
        if not self.analysis_ready():
            self.review_label.setText('请先核对主观题题干并点击确认核对，再允许 AI 作答。');return
        self.ai_enabled.setChecked(True)
        self.auto_answer.setChecked(True)
        self.essay_denied.discard(self.active_key)
        self.essay_permission=(self.active_key,self.payload['revision'],self.analysis_epoch)
        self.analyze_current()

    def deny_essay(self):
        if self.payload:self.essay_denied.add(self.payload['instance_key'])
        self.clear_analysis_display()
        self.review_label.setText('本题已选择手动作答，不会调用 AI、填写或提交；请在学生 Edge 中自行作答。')
