#!/usr/bin/env python3
"""
Study Notes Revision Tracker - PyQt5 desktop app (Windows-focused)

Save as: study_notes_pyqt.py

Requirements:
    pip install PyQt5 reportlab win10toast appdirs

Build to .exe (optional):
    pip install pyinstaller
    pyinstaller --onefile --windowed --name StudyNotes study_notes_pyqt.py

"""

import sys
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# Windows toast notifications
try:
    from win10toast import ToastNotifier
    toaster = ToastNotifier()
except Exception:
    toaster = None

# ----- CONFIG & STORAGE PATH -----
APP_NAME = "StudyNotes"
if sys.platform.startswith("win"):
    base_dir = Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming")
else:
    base_dir = Path.home()
DATA_DIR = base_dir / APP_NAME
DATA_FILE = DATA_DIR / "study_notes.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# ----- SAMPLE SUBJECTS (same as your HTML app) -----
SUBJECT_OPTIONS = [
    ("I64T001M01", "Occupational Health & Safety"),
    ("I64T001M02", "Fundamentals of Applied Electricity and Electronics -1"),
    ("I64T001M03", "Fundamentals of Communications – I"),
    ("I64T001M04", "Data Communication and Computer Networking – I"),
    ("I64T001M05", "Computer Structures and Programming Fundamentals"),
    ("I64T001M06", "Advanced Mathematics –I"),
    ("EMPM01", "Workplace Information Management"),
    ("EMPM02", "Workplace Communication Management"),
]

# ----- Helper I/O -----
def load_notes():
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_notes(notes):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(notes, f, indent=2, ensure_ascii=False)

def make_revision_dates(completion_date_str):
    # completion_date_str format: YYYY-MM-DD
    d = datetime.strptime(completion_date_str, "%Y-%m-%d")
    return {
        "24H": {"date": (d + timedelta(days=1)).strftime("%Y-%m-%d"), "completed": False},
        "3Days": {"date": (d + timedelta(days=3)).strftime("%Y-%m-%d"), "completed": False},
        "1Week": {"date": (d + timedelta(days=7)).strftime("%Y-%m-%d"), "completed": False},
        "1Month": {"date": (d + timedelta(days=30)).strftime("%Y-%m-%d"), "completed": False},
    }

# ----- Main Window -----
class MainWindow(QtWidgets.QMainWindow):
    CHECK_INTERVAL_MS = 60_000  # 60 seconds

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Study Notes — Desktop (PyQt)")
        self.resize(1100, 700)
        self.notes = load_notes()

        self._build_ui()
        self.refresh_table()
        self._start_timers()

    def _build_ui(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.setCentralWidget(w)

        # Header
        header = QtWidgets.QLabel("<h1>Study Notes Revision Tracker</h1>"
                                  "<div style='color:gray'>Local-first • PDF export • Windows notifications</div>")
        header.setTextFormat(QtCore.Qt.RichText)
        v.addWidget(header)

        # Top area: form + stats
        top = QtWidgets.QHBoxLayout()
        form_box = QtWidgets.QGroupBox("Add New Note")
        form_layout = QtWidgets.QFormLayout(form_box)

        # Subject select
        self.subject_combo = QtWidgets.QComboBox()
        self.subject_combo.addItem("-- Select a subject --", "")
        for code, name in SUBJECT_OPTIONS:
            self.subject_combo.addItem(f"{name} ({code})", f"{code}|{name}")
        form_layout.addRow("Subject:", self.subject_combo)

        # NOTE CODE with styled font
        self.note_code_input = QtWidgets.QLineEdit()
        # apply monospace + bold visually
        font = QtGui.QFont("Consolas", 10)
        font.setBold(True)
        self.note_code_input.setFont(font)
        self.note_code_input.setPlaceholderText("e.g., I64T001M01-01")
        form_layout.addRow("Note Code:", self.note_code_input)

        # Completion date (default today)
        self.completion_date = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.completion_date.setCalendarPopup(True)
        form_layout.addRow("Completion Date:", self.completion_date)

        add_btn = QtWidgets.QPushButton("Add Note")
        add_btn.clicked.connect(self.add_note)
        form_layout.addRow(add_btn)

        top.addWidget(form_box, 0)

        # Stats box
        stats_box = QtWidgets.QGroupBox("Stats")
        stats_layout = QtWidgets.QVBoxLayout(stats_box)
        self.total_label = QtWidgets.QLabel("Total notes: 0")
        self.pending_label = QtWidgets.QLabel("Pending revisions: 0")
        self.completed_label = QtWidgets.QLabel("Completed revisions: 0")
        stats_layout.addWidget(self.total_label)
        stats_layout.addWidget(self.pending_label)
        stats_layout.addWidget(self.completed_label)
        top.addWidget(stats_box, 0)

        # Notification enable checkbox
        notif_box = QtWidgets.QGroupBox("Notifications")
        nlayout = QtWidgets.QVBoxLayout(notif_box)
        self.enable_notifications_cb = QtWidgets.QCheckBox("Enable Windows notifications")
        self.enable_notifications_cb.setChecked(True)
        nlayout.addWidget(self.enable_notifications_cb)
        top.addWidget(notif_box, 0)

        v.addLayout(top)

        # Tab widget: All, Pending, All Done
        self.tabs = QtWidgets.QTabWidget()
        self.tab_all = QtWidgets.QWidget()
        self.tab_pending = QtWidgets.QWidget()
        self.tab_alldone = QtWidgets.QWidget()
        self.tabs.addTab(self.tab_all, "All")
        self.tabs.addTab(self.tab_pending, "Pending")
        self.tabs.addTab(self.tab_alldone, "All Done")
        v.addWidget(self.tabs, 1)

        # Each tab contains the same table UI; reuse a function to create
        self.table_all = self._create_table_widget()
        self.table_pending = self._create_table_widget()
        self.table_alldone = self._create_table_widget()

        lay_all = QtWidgets.QVBoxLayout(self.tab_all)
        lay_all.addWidget(self._make_toolbar(self.refresh_table))
        lay_all.addWidget(self.table_all)

        lay_pending = QtWidgets.QVBoxLayout(self.tab_pending)
        lay_pending.addWidget(self._make_toolbar(self.refresh_table))
        lay_pending.addWidget(self.table_pending)

        lay_alldone = QtWidgets.QVBoxLayout(self.tab_alldone)
        lay_alldone.addWidget(self._make_toolbar(self.refresh_table))
        lay_alldone.addWidget(self.table_alldone)

    def _make_toolbar(self, refresh_cb):
        widget = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(widget)
        h.setContentsMargins(0, 0, 0, 0)
        btn_pdf = QtWidgets.QPushButton("Export PDF")
        btn_pdf.clicked.connect(self.export_pdf)
        btn_json = QtWidgets.QPushButton("Export JSON")
        btn_json.clicked.connect(self.export_json)
        btn_csv = QtWidgets.QPushButton("Export CSV")
        btn_csv.clicked.connect(self.export_csv)
        btn_refresh = QtWidgets.QPushButton("Refresh")
        btn_refresh.clicked.connect(refresh_cb)
        h.addWidget(btn_pdf)
        h.addWidget(btn_json)
        h.addWidget(btn_csv)
        h.addStretch()
        h.addWidget(btn_refresh)
        return widget

    def _create_table_widget(self):
        tbl = QtWidgets.QTableWidget()
        tbl.setColumnCount(8)
        tbl.setHorizontalHeaderLabels([
            "Subject", "Note Code", "Completion Date",
            "24H", "3 Days", "1 Week", "1 Month", "Action"
        ])
        tbl.horizontalHeader().setStretchLastSection(True)
        tbl.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        tbl.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        return tbl

    def add_note(self):
        data = self.subject_combo.currentData()
        if not data:
            QtWidgets.QMessageBox.warning(self, "Missing subject", "Please select a subject.")
            return
        code, name = data.split("|")
        note_code = self.note_code_input.text().strip()
        if not note_code:
            QtWidgets.QMessageBox.warning(self, "Missing code", "Please enter the note code.")
            return
        qdate = self.completion_date.date()
        completion_date = qdate.toString("yyyy-MM-dd")
        revisions = make_revision_dates(completion_date)

        new_note = {
            "id": int(datetime.now().timestamp() * 1000),
            "subjectName": name,
            "noteCode": note_code,
            "completionDate": completion_date,
            "revisions": revisions
        }
        self.notes.append(new_note)
        save_notes(self.notes)
        self.note_code_input.clear()
        self.subject_combo.setCurrentIndex(0)
        self.completion_date.setDate(QtCore.QDate.currentDate())
        self.refresh_table()

    def refresh_table(self):
        # update stats
        self._update_stats()

        # Fill tables according to tab type
        self._fill_table(self.table_all, lambda n: True)
        self._fill_table(self.table_pending, lambda n: not self._is_all_done(n))
        self._fill_table(self.table_alldone, lambda n: self._is_all_done(n))

    def _update_stats(self):
        total = len(self.notes)
        pending = 0
        completed = 0
        for n in self.notes:
            for r in n["revisions"].values():
                if r.get("completed"):
                    completed += 1
                else:
                    pending += 1
        self.total_label.setText(f"Total notes: {total}")
        self.pending_label.setText(f"Pending revisions: {pending}")
        self.completed_label.setText(f"Completed revisions: {completed}")

    def _is_all_done(self, note):
        return all(r.get("completed") for r in note["revisions"].values())

    def _fill_table(self, table, filter_fn):
        table.setRowCount(0)
        rows = [n for n in self.notes if filter_fn(n)]
        if not rows:
            table.setRowCount(0)
            return

        table.setRowCount(len(rows))
        for ri, note in enumerate(rows):
            subject_item = QtWidgets.QTableWidgetItem(note["subjectName"])
            code_item = QtWidgets.QTableWidgetItem(note["noteCode"])
            # make code visually monospace and bold
            code_item.setFont(QtGui.QFont("Consolas", 10, QtGui.QFont.Bold))
            completion_item = QtWidgets.QTableWidgetItem(note["completionDate"])

            table.setItem(ri, 0, subject_item)
            table.setItem(ri, 1, code_item)
            table.setItem(ri, 2, completion_item)

            # revision columns: put date + a toggle button
            for ci, key in enumerate(["24H", "3Days", "1Week", "1Month"], start=3):
                rev = note["revisions"][key]
                widget = QtWidgets.QWidget()
                layout = QtWidgets.QHBoxLayout(widget)
                layout.setContentsMargins(4, 2, 4, 2)
                lbl = QtWidgets.QLabel(datetime.strptime(rev["date"], "%Y-%m-%d").strftime("%d %b"))
                btn = QtWidgets.QPushButton("Done" if not rev.get("completed") else "Undo")
                btn.setProperty("note_id", note["id"])
                btn.setProperty("rev_key", key)
                btn.clicked.connect(self._toggle_revision)
                # highlight styles for overdue / today
                today = datetime.now().date()
                rev_date = datetime.strptime(rev["date"], "%Y-%m-%d").date()
                if rev.get("completed"):
                    lbl.setStyleSheet("color: green; font-weight:600")
                elif rev_date < today:
                    lbl.setStyleSheet("color: red; font-weight:600")
                elif rev_date == today:
                    lbl.setStyleSheet("color: orange; font-weight:600")
                layout.addWidget(lbl)
                layout.addStretch()
                layout.addWidget(btn)
                table.setCellWidget(ri, ci, widget)

            # action column: delete button
            widget_action = QtWidgets.QWidget()
            hact = QtWidgets.QHBoxLayout(widget_action)
            hact.setContentsMargins(4, 2, 4, 2)
            del_btn = QtWidgets.QPushButton("Delete")
            del_btn.setProperty("note_id", note["id"])
            del_btn.clicked.connect(self._delete_note)
            hact.addWidget(del_btn)
            table.setCellWidget(ri, 7, widget_action)

        table.resizeColumnsToContents()

    def _toggle_revision(self):
        btn = self.sender()
        note_id = btn.property("note_id")
        key = btn.property("rev_key")
        for n in self.notes:
            if n["id"] == note_id:
                n["revisions"][key]["completed"] = not n["revisions"][key].get("completed", False)
                save_notes(self.notes)
                self.refresh_table()
                return

    def _delete_note(self):
        btn = self.sender()
        note_id = btn.property("note_id")
        ret = QtWidgets.QMessageBox.question(self, "Delete", "Are you sure you want to delete this note?",
                                             QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if ret == QtWidgets.QMessageBox.Yes:
            self.notes = [n for n in self.notes if n["id"] != note_id]
            save_notes(self.notes)
            self.refresh_table()

    def export_pdf(self):
        if not self.notes:
            QtWidgets.QMessageBox.information(self, "Export", "No notes to export.")
            return
        desktop = Path.home() / "Desktop"
        fname = desktop / f"study-notes-{int(datetime.now().timestamp())}.pdf"
        doc = SimpleDocTemplate(str(fname), pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
        styles = getSampleStyleSheet()
        story = []
        story.append(Paragraph("Study Notes — Revision Tracker", styles["Title"]))
        story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles["Normal"]))
        story.append(Spacer(1, 12))

        table_data = [["Code", "Module", "Completed", "24H", "3 Days", "1 Week", "1 Month"]]
        for n in self.notes:
            row = [
                n["noteCode"],
                n["subjectName"],
                n["completionDate"],
                f"{n['revisions']['24H']['date']}{' ✓' if n['revisions']['24H']['completed'] else ''}",
                f"{n['revisions']['3Days']['date']}{' ✓' if n['revisions']['3Days']['completed'] else ''}",
                f"{n['revisions']['1Week']['date']}{' ✓' if n['revisions']['1Week']['completed'] else ''}",
                f"{n['revisions']['1Month']['date']}{' ✓' if n['revisions']['1Month']['completed'] else ''}"
            ]
            table_data.append(row)

        t = Table(table_data, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#6A11CB")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(t)
        story.append(Spacer(1,12))

        # stats
        total = len(self.notes)
        pending = sum(1 for n in self.notes for r in n["revisions"].values() if not r.get("completed"))
        completed = sum(1 for n in self.notes for r in n["revisions"].values() if r.get("completed"))
        story.append(Paragraph(f"Total notes: {total} — Pending revisions: {pending} — Completed revisions: {completed}", styles["Normal"]))

        doc.build(story)
        QtWidgets.QMessageBox.information(self, "Export", f"PDF saved to: {fname}")

    def export_json(self):
        if not self.notes:
            QtWidgets.QMessageBox.information(self, "Export", "No notes to export.")
            return
        desktop = Path.home() / "Desktop"
        fname = desktop / f"study-notes-{int(datetime.now().timestamp())}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(self.notes, f, indent=2, ensure_ascii=False)
        QtWidgets.QMessageBox.information(self, "Export", f"JSON saved to: {fname}")

    def export_csv(self):
        if not self.notes:
            QtWidgets.QMessageBox.information(self, "Export", "No notes to export.")
            return
        desktop = Path.home() / "Desktop"
        fname = desktop / f"study-notes-{int(datetime.now().timestamp())}.csv"
        lines = ["Subject,Note Code,Completion Date,24H Date,24H Status,3Days Date,3Days Status,1Week Date,1Week Status,1Month Date,1Month Status"]
        for n in self.notes:
            row = [
                n["subjectName"].replace('"', '""'),
                n["noteCode"].replace('"', '""'),
                n["completionDate"],
                n["revisions"]["24H"]["date"], str(n["revisions"]["24H"].get("completed", False)),
                n["revisions"]["3Days"]["date"], str(n["revisions"]["3Days"].get("completed", False)),
                n["revisions"]["1Week"]["date"], str(n["revisions"]["1Week"].get("completed", False)),
                n["revisions"]["1Month"]["date"], str(n["revisions"]["1Month"].get("completed", False)),
            ]
            lines.append(",".join(f'"{c}"' for c in row))
        with open(fname, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        QtWidgets.QMessageBox.information(self, "Export", f"CSV saved to: {fname}")

    def _start_timers(self):
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._check_due_revisions)
        self.timer.start(self.CHECK_INTERVAL_MS)
        # run immediately once
        QtCore.QTimer.singleShot(2000, self._check_due_revisions)

    def _check_due_revisions(self):
        if not self.enable_notifications_cb.isChecked():
            return
        if toaster is None:
            # toaster unavailable; skip notifications
            return
        now = datetime.now().date()
        for n in self.notes:
            for key, rev in n["revisions"].items():
                if rev.get("completed"):
                    continue
                rev_date = datetime.strptime(rev["date"], "%Y-%m-%d").date()
                # Notify if revision is today or within next 24 hours
                if rev_date == now or (rev_date - now).days == 1:
                    # Use win10toast for Windows toast
                    title = "Revision Reminder"
                    body = f"{n['noteCode']} — {key} due {rev['date']}"
                    try:
                        toaster.show_toast(title, body, duration=8, threaded=True)
                    except Exception:
                        pass

def main():
    app = QtWidgets.QApplication(sys.argv)
    mw = MainWindow()
    mw.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
