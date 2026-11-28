"""PlateBridge desktop review and batch export."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
from pathlib import Path
import queue
import re
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import plateproject as core
from plate_review import differences, inspect_project


def discover(paths):
    outputs = re.compile(r" (Creator 5|AD5X|Adventurer 5M Pro)( \(\d+\))?$", re.I)
    found = {}
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for f in sorted(p.rglob("*.3mf")):
                if f.is_file() and not outputs.search(f.stem):
                    found[f.resolve()] = None
        elif p.is_file() and p.suffix.lower() == ".3mf":
            found[p.resolve()] = None
    return list(found)


def signature(path):
    info = path.stat()
    return info.st_size, info.st_mtime_ns


@dataclass
class Job:
    path: Path
    status: str = "Queued"
    detail: str = ""
    stamp: tuple = ()
    maps: dict = field(default_factory=dict)
    saved: dict = field(default_factory=dict)
    denied: bool = False


def launch(drop_support):
    root = tk.Tk()
    Window(root, drop_support)
    root.mainloop()


class Window:
    def __init__(self, root, drop_support):
        self.root = root
        root.title("PlateBridge")
        root.iconbitmap(str(Path(__file__).with_name("PlateBridge.ico")))
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.events = queue.Queue()
        self.jobs = {}
        self.cache = OrderedDict()
        self.reading = set()
        self.saving = False
        self.closed = False
        self.printer = tk.StringVar(value=core.PRINTERS[0])
        self.notice = tk.StringVar(value="Ready")
        self.source_name = tk.StringVar(value="Drop a .3mf file here")
        self.title = tk.StringVar(value="Plate review")
        self.advanced = tk.Toplevel(root)
        self.advanced.withdraw()
        self.advanced.title("PlateBridge · Advanced")
        self.advanced.protocol("WM_DELETE_WINDOW", self.hide_advanced)
        self.advanced.bind("<Escape>", lambda _: self.hide_advanced())
        self.build_main()
        self.build_advanced()
        try:
            drop_support(root, self.add)
        except OSError:
            self.notice.set("Use Browse files to choose your project.")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(80, self.poll)
        self.buttons()

    def build_main(self):
        shell, bezel, lcd = "#58458C", "#222032", "#D1E3AC"
        ink, muted = "#253B31", "#50674D"
        self.root.configure(bg=shell)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Treeview", rowheight=25, font=("Segoe UI", 9))
        style.map("Treeview", background=[("selected", "#24675B")], foreground=[("selected", "white")])
        style.configure("Pocket.Horizontal.TProgressbar", background=ink, troughcolor="#ADBF91",
                        lightcolor=ink, darkcolor=ink, borderwidth=0, thickness=5)
        for name, bg, fg, active in (("Save", "#FFD879", "#292235", "#FFE9AE"),
                                     ("Studio", "#302745", "#FFFFFF", "#49395F")):
            style.configure(name + ".TButton", background=bg, foreground=fg, padding=(14, 9),
                            borderwidth=1, font=("Segoe UI", 10, "bold"))
            style.map(name + ".TButton", background=[("disabled", "#544969"), ("active", active)],
                      foreground=[("disabled", "#D7CDDF")])

        panel = tk.Frame(self.root, bg=shell, padx=24, pady=18)
        panel.pack(fill="both", expand=True)
        header = tk.Frame(panel, bg=shell)
        header.pack(fill="x", pady=(0, 12))
        tk.Label(header, text="PlateBridge", fg="white", bg=shell,
                 font=("Segoe UI", 23, "bold italic")).pack(side="left")
        for tone in ("#F39EBA", "#FFDA82", "#9ADAC9"):
            tk.Frame(header, bg=tone, width=7, height=14).pack(side="right", padx=2)
        bezel_frame = tk.Frame(panel, bg=bezel, padx=10, pady=10)
        bezel_frame.pack(fill="x")
        screen = tk.Frame(bezel_frame, bg=lcd, padx=18, pady=14)
        screen.pack(fill="both", expand=True)
        tk.Label(screen, text="SOURCE PROJECT", bg=lcd, fg=muted,
                 font=("Consolas", 10, "bold")).pack(anchor="w")
        source_row = tk.Frame(screen, bg=lcd)
        source_row.pack(fill="x", pady=(10, 9))
        art = tk.Canvas(source_row, width=40, height=46, bg=lcd, highlightthickness=0)
        art.pack(side="left", padx=(0, 12))
        for y, bits in enumerate(("011111110", "110000011", "110111011", "110111011", "110000011",
                                  "111111111", "110000011", "110110011", "110110011", "011111110")):
            for x, bit in enumerate(bits):
                if bit == "1":
                    art.create_rectangle(4*x, 4*y, 4*x+4, 4*y+4, fill=ink, outline="")
        tk.Label(source_row, textvariable=self.source_name, fg=ink, bg=lcd, wraplength=375, anchor="w",
                 font=("Consolas", 15, "bold"), justify="left").pack(side="left", fill="x", expand=True)
        tk.Button(screen, text="Browse files…", command=self.pick_files, bg=lcd, fg=ink,
                  activebackground="#B9CF95", relief="solid", bd=1, padx=12, pady=3,
                  font=("Segoe UI", 10)).pack(anchor="w")
        self.bar = ttk.Progressbar(screen, mode="indeterminate", style="Pocket.Horizontal.TProgressbar")
        self.bar.pack(fill="x", pady=(12, 4))
        tk.Label(screen, textvariable=self.notice, fg=ink, bg=lcd, font=("Consolas", 10),
                 wraplength=430, justify="left").pack(anchor="w")
        tk.Label(panel, text="DESTINATION PRINTER", fg="white", bg=shell,
                 font=("Consolas", 10, "bold")).pack(anchor="w", pady=(15, 6))
        choices = tk.Frame(panel, bg=shell)
        choices.pack(fill="x")
        self.pickers = []
        for column, name in enumerate(core.PRINTERS):
            choices.columnconfigure(column, weight=1)
            button = tk.Radiobutton(choices, text=name, value=name, variable=self.printer,
                                    command=self.refresh, indicatoron=False, bg="#3B305D", fg="white",
                                    selectcolor="#205B52", activebackground="#4B416E", activeforeground="white",
                                    font=("Segoe UI", 10, "bold"), bd=1, relief="flat", padx=7, pady=8)
            button.grid(row=0, column=column, sticky="ew", padx=(0, 3))
            self.pickers.append(button)
        actions = tk.Frame(panel, bg=shell)
        actions.pack(fill="x", pady=(16, 0))
        self.save = ttk.Button(actions, text="Save project", style="Save.TButton", command=lambda: self.export(False))
        self.save.pack(side="right")
        self.open_button = ttk.Button(actions, text="Open in Flash Studio", style="Studio.TButton",
                                      command=lambda: self.open_saved(False))
        self.open_button.pack(side="right", padx=6)
        self.advanced_button = tk.Button(actions, text="Advanced…", command=self.show_advanced,
                                         bg=shell, fg="#F6EFFC", activebackground="#473571",
                                         activeforeground="white", relief="flat", cursor="hand2",
                                         font=("Segoe UI", 10, "underline"), padx=2, pady=4)
        self.advanced_button.pack(side="left")
        self.root.update_idletasks()
        self.root.minsize(max(510, panel.winfo_reqwidth()), panel.winfo_reqheight())

    def show_advanced(self):
        self.advanced.deiconify()
        self.advanced.lift()
        self.advanced.focus_set()
        self.refresh()

    def hide_advanced(self):
        self.advanced.withdraw()
        self.root.lift()
        self.advanced_button.focus_set()

    def build_advanced(self):
        window = self.advanced
        window.configure(bg="#58458C")
        window.geometry("950x530")
        window.minsize(720, 430)
        header = tk.Frame(window, bg="#58458C", padx=12, pady=7)
        header.pack(fill="x")
        tk.Label(header, text="Advanced", bg="#58458C", fg="white",
                 font=("Segoe UI", 15, "bold italic")).pack(side="left")
        ttk.Button(header, text="Add folder…", command=self.pick_folder).pack(side="right")
        row = ttk.Frame(window, padding=(10, 6))
        row.pack(fill="x", side="bottom")
        self.folder_button = ttk.Button(row, text="Show in folder", command=lambda: self.open_saved(True))
        self.folder_button.pack(side="left")
        ttk.Button(row, text="Done", command=self.hide_advanced).pack(side="right")
        self.batch = ttk.Button(row, text="Save batch", command=lambda: self.export(True))
        self.batch.pack(side="right", padx=5)
        self.alternate = ttk.Button(row, text="Save copy as…", command=self.save_elsewhere)
        body = ttk.Panedwindow(window, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        left=ttk.Frame(body,padding=7)
        right=ttk.Frame(body,padding=7)
        body.add(left,weight=1)
        body.add(right,weight=3)
        ttk.Label(left,text="Project queue",font=("Segoe UI",11,"bold")).pack(anchor="w")
        self.files=self.table(left,("Project","Status"),(165,77),height=9)
        self.files.bind("<<TreeviewSelect>>",lambda _:self.select_job())
        ttk.Button(left,text="Remove selected",command=self.remove).pack(anchor="w",pady=(6,0))
        self.advanced_printer = ttk.Combobox(right, textvariable=self.printer, values=core.PRINTERS,
                                            state="readonly", width=22)
        self.advanced_printer.pack(anchor="w")
        self.advanced_printer.bind("<<ComboboxSelected>>", lambda _: self.refresh())
        ttk.Label(right,textvariable=self.title,font=("Segoe UI",10,"bold"),wraplength=560).pack(anchor="w",pady=(7,4))
        pages=ttk.Notebook(right)
        self.pages = pages
        pages.pack(fill="both",expand=True)
        plates,compare,settings=(ttk.Frame(pages,padding=6) for _ in range(3))
        for tab,title in [(plates,"Plates & spools"),(compare,"Compare printers"),(settings,"Settings")]:
            pages.add(tab,text=title)
        self.plates=self.table(plates,("Plate","Bed fit","Colors"),(145,100,55),height=5)
        self.plates.bind("<<TreeviewSelect>>",lambda _:self.show_plate())
        self.detail=tk.Text(plates,height=4,wrap="word",font=("Segoe UI",9),relief="flat",bg="#E7EFDA")
        self.detail.pack(fill="both",pady=5)
        ttk.Button(plates,text="Map plate colors…",command=self.spools).pack(anchor="e")
        self.compare=self.table(compare,("Printer","Fit as placed","Need reload¹"),(145,95,110))
        ttk.Label(compare,text="¹ Plates using more material colors than available spool positions. Double-click a printer to see its plates.",
                  wraplength=465).pack(anchor="w",pady=6)
        self.compare.bind("<Double-1>",self.choose_comparison)
        self.compare.bind("<Return>",self.choose_comparison)
        self.settings=self.table(settings,("Setting","Original","Converted","Result"),(130,115,115,78))
        self.settings.bind("<Double-1>",self.full_setting)
        self.settings.bind("<Return>",self.full_setting)

    @staticmethod
    def table(parent, headings, widths, height=8):
        panel=ttk.Frame(parent)
        panel.pack(fill="both",expand=True)
        tree=ttk.Treeview(panel,columns=headings,show="headings",selectmode="browse",height=height)
        for col,width in zip(headings,widths):
            tree.heading(col,text=col)
            tree.column(col,width=width,minwidth=42)
        bar=ttk.Scrollbar(panel,orient="vertical",command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right",fill="y")
        tree.pack(side="left",fill="both",expand=True)
        return tree

    def pick_folder(self):
        path=filedialog.askdirectory(parent=self.advanced)
        if path:self.add([path])

    def pick_files(self):
        self.add(filedialog.askopenfilenames(parent=self.root,filetypes=[("3MF project","*.3mf")]))

    def submit(self, action, done):
        future=self.pool.submit(action)
        future.add_done_callback(lambda f:self.events.put((done,f)))

    def poll(self):
        while not self.events.empty():
            done,f=self.events.get_nowait()
            done(f)
        if not self.closed:self.root.after(80,self.poll)

    def close(self):
        self.closed=True
        self.pool.shutdown(wait=False,cancel_futures=True)
        self.root.destroy()

    def add(self, paths):
        if not paths:return
        self.notice.set("Finding 3MF projects…")
        def found(f):
            try: paths=f.result()
            except Exception as e:
                self.notice.set(str(e))
                return
            first = str(paths[0]) if paths else None
            for p in paths:
                key=str(p)
                if key not in self.jobs:
                    self.jobs[key]=Job(p)
                    self.files.insert("","end",iid=key,values=(p.name,"Queued"))
            if first:
                self.files.selection_set(first)
                self.files.see(first)
                self.notice.set("Checking project..." if len(paths) == 1 else f"{len(paths)} projects selected. Open Advanced to save the batch.")
            else:self.notice.set("No new 3MF projects found.")
            self.buttons()
        self.submit(lambda:discover(paths),found)

    def selected(self):
        selected=self.files.selection()
        return self.jobs.get(selected[0]) if selected else None

    def remove(self):
        job=self.selected()
        if self.saving or not job:return
        key=str(job.path)
        del self.jobs[key]
        self.cache.pop(key,None)
        self.files.delete(key)
        if self.files.get_children():self.files.selection_set(self.files.get_children()[0])
        self.refresh()

    def update_row(self,job,status,detail=""):
        job.status,job.detail=status,detail
        if self.jobs.get(str(job.path)) is job:
            self.files.item(str(job.path),values=(job.path.name,status))

    def remember(self,job,report,stamp):
        key=str(job.path)
        if job.stamp != stamp:
            job.maps.clear()
            job.saved.clear()
            old=report["previous"]
            if old.get("printer") in core.PRINTERS:
                job.maps[old["printer"]]={int(p):{int(c):int(s) for c,s in m.items()}
                                          for p,m in old.get("plates",{}).items()}
        job.stamp=stamp
        self.cache[key]=report
        self.cache.move_to_end(key)
        while len(self.cache)>6:self.cache.popitem(last=False)

    def select_job(self):
        job=self.selected()
        self.refresh()
        if not job:
            self.notice.set("Ready")
            return
        if self.saving:return
        key=str(job.path)
        if key in self.reading:return
        try: stamp=signature(job.path)
        except OSError as e:
            self.update_row(job,"Error",str(e))
            self.refresh()
            return
        if key in self.cache and stamp == job.stamp:
            self.refresh()
            return
        self.reading.add(key)
        self.update_row(job,"Reading")
        self.notice.set(f"Measuring {job.path.name}…")
        self.bar.start(14)
        def reviewed(f):
            self.reading.discard(key)
            if not self.reading and not self.saving:self.bar.stop()
            if self.jobs.get(key) is not job:return
            try:
                self.remember(job,f.result(),stamp)
                self.update_row(job,"Reviewed")
            except Exception as e:self.update_row(job,"Error",str(e))
            if self.selected() is job:
                self.notice.set(job.detail or "Ready to save")
                self.refresh()
        self.submit(lambda:inspect_project(job.path),reviewed)

    def buttons(self):
        job=self.selected()
        report = self.cache.get(str(job.path)) if job else None
        ready = report and self.printer.get() in report["targets"] 
        for widget,on in [(self.save,ready and not self.saving),(self.batch,len(self.jobs)>1 and not self.saving),
                          (self.open_button,job and self.printer.get() in job.saved),
                          (self.folder_button,job and self.printer.get() in job.saved)]:
            widget.state(["!disabled" if on else "disabled"])
        for w in self.pickers:
            w.configure(state="disabled" if self.saving else "normal")
        self.advanced_printer.configure(state="disabled" if self.saving else "readonly")
        count = len(self.jobs)
        self.advanced_button.configure(text=f"Advanced ({count})…" if count > 1 else "Advanced…")
        if job and job.denied:self.alternate.pack(side="right")
        else:self.alternate.pack_forget()

    @staticmethod
    def clear(tree):
        tree.delete(*tree.get_children())

    def refresh(self):
        job=self.selected()
        for table in (self.plates,self.compare,self.settings):self.clear(table)
        self.source_name.set(job.path.name if job else "Drop a .3mf file here")
        self.title.set(str(job.path) if job else "Plate review")
        self.buttons()
        report = self.cache.get(str(job.path)) if job else None
        if job and not self.saving:
            if job.status == "Error":
                self.notice.set(job.detail)
            elif report:
                problem = report["errors"].get(self.printer.get())
                if problem or job.status == "Reviewed":
                    self.notice.set(problem or "Ready to save")
                    self.files.item(str(job.path), values=(job.path.name, "Unavailable" if problem else job.status))
        if self.advanced.state() == "withdrawn":
            return
        self.show_text(job.detail if job else "")
        r=self.cache.get(str(job.path)) if job else None
        if not r:return
        printer=self.printer.get()
        total=sum(bool(p["parts"]) for p in r["plates"])
        counts={k:sum(bool(p["parts"]) and not p["issues"][k] for p in r["plates"]) for k in r["targets"]}
        for k in core.PRINTERS:
            if k not in counts:
                self.compare.insert("","end",iid=k,values=(k,"Unavailable","—"))
                continue
            swaps=sum(len(p["colors"])>core.PRESETS[k][3] for p in r["plates"])
            uncertain=any(p["uncertain"] for p in r["plates"])
            self.compare.insert("","end",iid=k,values=(k,f"{counts[k]} / {total}",str(swaps)+(" + review" if uncertain else "")),
                                tags=("best",) if counts[k]==max(counts.values()) else ())
        self.compare.tag_configure("best",background="#D8E7B8")
        if printer in r["errors"]:
            self.show_text(r["errors"][printer])
            return
        for i,p in enumerate(r["plates"],1):
            fit="Empty" if not p["parts"] else "Check fit" if p["issues"][printer] else "Fits"
            self.plates.insert("","end",iid=str(i),values=(p["name"],fit,str(len(p["colors"]))+("+" if p["uncertain"] else "")))
        if self.plates.get_children():self.plates.selection_set("1")
        for k,b,a,status in differences(r,printer):
            self.settings.insert("","end",iid=k,values=(k.replace("_"," "),self.brief(b),self.brief(a),status))

    @staticmethod
    def brief(v):
        if v is None:return "—"
        return (" · ".join(map(str,v)) if isinstance(v,list) else str(v)).replace("\n"," ")[:100]

    def full_setting(self,_):
        job=self.selected()
        sel=self.settings.selection()
        if not sel or not job:return
        k=sel[0]
        r=self.cache[str(job.path)]
        win=tk.Toplevel(self.advanced)
        win.title(k.replace("_"," "))
        box=tk.Text(win,wrap="word",width=70,height=18)
        box.pack(fill="both",expand=True)
        for label,settings in (("Original",r["source"]),("Converted",r["targets"][self.printer.get()])):
            box.insert("end",label+"\n"+json.dumps(settings.get(k),ensure_ascii=False,indent=2)+"\n\n")
        box.configure(state="disabled")

    def choose_comparison(self,_):
        if self.saving:return
        sel=self.compare.selection()
        if sel:
            self.printer.set(sel[0])
            self.refresh()
            self.pages.select(0)

    def show_text(self,text):
        self.detail.configure(state="normal")
        self.detail.delete("1.0","end")
        self.detail.insert("1.0",text)
        self.detail.configure(state="disabled")

    def plate_selection(self):
        job=self.selected()
        sel=self.plates.selection()
        if job and sel and str(job.path) in self.cache:
            return job,self.cache[str(job.path)],int(sel[0])

    def show_plate(self):
        selected=self.plate_selection()
        if not selected:return
        job,r,n=selected
        p=r["plates"][n-1];printer=self.printer.get()
        issues=p["issues"].get(printer,[])
        lines=list(issues) or [f'{p["parts"]} printable object(s) inside the build volume.' if p["parts"] else "Empty plate."]
        palette=r["source"]["filament_colour"]
        plan=job.maps.get(printer,{}).get(n,{})
        lines.append("Colors  "+", ".join(f"{i} {palette[i-1]}"+(f" → spool {plan[i]}" if i in plan else "") for i in p["colors"]))
        if len(p["colors"])>core.PRESETS[printer][3]:lines.append("More colors than loaded positions. Plan a reload or merge colors in Flash Studio.")
        if p["uncertain"]:lines.append("Additional colors may be used by modifiers or unrecognized paint. Verify in the slice preview.")
        self.show_text("\n".join(lines))

    def spools(self):
        selected=self.plate_selection()
        if not selected or self.saving:return
        job,r,n=selected;printer=self.printer.get()
        p=r["plates"][n-1]
        colors=list(range(1,len(r["source"]["filament_colour"])+1)) if p["uncertain"] else p["colors"]
        if not colors:return
        win=tk.Toplevel(self.advanced)
        win.title(f"{p['name']} · spool assignments")
        win.transient(self.advanced);win.grab_set()
        ttk.Label(win,text="Choose the loaded spool for each project color.",padding=8).pack()
        canvas=tk.Canvas(win,width=365,height=min(280,32*len(colors)),highlightthickness=0)
        canvas.pack(side="top",fill="both",expand=True)
        inner=ttk.Frame(canvas)
        canvas.create_window((0,0),window=inner,anchor="nw")
        fields={}
        old=job.maps.get(printer,{}).get(n,{})
        capacity=core.PRESETS[printer][3]
        for row,c in enumerate(colors):
            color=r["source"]["filament_colour"][c-1]
            tk.Label(inner,bg=color[:7] if re.fullmatch(r"#[0-9a-fA-F]{6,8}",color) else "gray",width=2).grid(row=row,column=0,padx=4)
            ttk.Label(inner,text=f"{c} · {color} · {r['source']['filament_type'][c-1]}").grid(row=row,column=1,sticky="w")
            v=tk.StringVar(value=str(old.get(c,"Auto")))
            ttk.Combobox(inner,textvariable=v,values=("Auto",*map(str,range(1,capacity+1))),state="readonly",width=8).grid(row=row,column=2,pady=2,padx=8)
            fields[c]=v
        inner.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))
        scroll=ttk.Scrollbar(win,orient="vertical",command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        if len(colors)>8:scroll.place(in_=canvas,relx=1,rely=0,relheight=1,anchor="ne")
        note=("Creator 5 assignments are written as manual tool mappings. Set every used color to apply a manual map."
              if printer=="Creator 5" else "Studio shows this plan in the plate name. Match the spool positions when sending the plate.")
        ttk.Label(win,text=note,wraplength=340,padding=8).pack()
        def apply():
            mapping={c:int(v.get()) for c,v in fields.items() if v.get()!="Auto"}
            if printer=="Creator 5" and mapping and len(mapping)!=len(fields):
                messagebox.showinfo("Complete the map","Choose a spool for each used color, or set every color to Auto.",parent=win)
                return
            if len(set(mapping.values()))<len(mapping) and not messagebox.askyesno("Share a spool?",
                    "Several project colors will use the same spool. Save this assignment?",parent=win):return
            plans=job.maps.setdefault(printer,{})
            if mapping:plans[n]=mapping
            else:plans.pop(n,None)
            job.saved.pop(printer,None)
            self.update_row(job,"Reviewed")
            win.destroy();self.show_plate();self.buttons()
        ttk.Button(win,text="Apply to plate",command=apply).pack(pady=6)

    def save_elsewhere(self):
        job=self.selected()
        if not job or self.saving:return
        name=filedialog.asksaveasfilename(parent=self.root,initialfile=f"{job.path.stem} {self.printer.get()}.3mf",
                                          defaultextension=".3mf",filetypes=[("3MF project","*.3mf")])
        if name:self.export(False,Path(name))

    def export(self,batch,destination=None):
        if self.saving:return
        jobs=list(self.jobs.values()) if batch else [self.selected()]
        printer=self.printer.get()
        if batch:
            pending = []
            for job in jobs:
                saved = job.saved.get(printer)
                try:
                    current = saved and saved.is_file() and job.stamp == signature(job.path)
                except OSError:
                    current = False
                if not current:
                    pending.append(job)
            jobs = pending
        else:
            jobs = [job for job in jobs if job]
        if not jobs:
            self.notice.set("Every queued project already has a saved copy for this printer.")
            return
        self.saving=True;self.buttons();self.bar.start(14)
        def next_job(index,ok):
            if self.closed:return
            if index==len(jobs):
                self.saving=False;self.bar.stop();self.buttons()
                if len(jobs) == 1:
                    job = jobs[0]
                    self.notice.set(f"Saved {job.saved[printer].name}" if ok else job.detail)
                else:
                    self.notice.set(f"Saved {ok} of {len(jobs)} projects. See Advanced for results.")
                self.refresh()
                return
            job=jobs[index];key=str(job.path)
            self.notice.set(f"Saving {index+1} of {len(jobs)}…" if batch else "Saving project…")
            self.update_row(job,"Saving")
            cached=self.cache.get(key)
            old_stamp=job.stamp
            maps=dict(job.maps.get(printer,{}))
            def write():
                stamp=signature(job.path)
                if stamp!=old_stamp and maps:
                    raise ValueError("The source changed. Select it again and review the spool plan.")
                report=cached if cached and old_stamp==stamp else inspect_project(job.path)
                if printer in report["errors"]:raise ValueError(report["errors"][printer])
                previous=report["previous"]
                plan=maps
                if printer not in job.maps and previous.get("printer")==printer:
                    plan={int(n):{int(c):int(s) for c,s in m.items()} for n,m in previous.get("plates",{}).items()}
                out=destination or job.path.with_name(f"{job.path.stem} {printer}.3mf")
                if signature(job.path)!=stamp:raise ValueError("The source changed during review. Try again.")
                return report,stamp,core.convert_project(job.path,out,printer,plan)
            def finished(f):
                try:
                    r,stamp,out=f.result()
                    self.remember(job,r,stamp);job.saved[printer]=out;job.denied=False
                    self.update_row(job,"Saved",str(out));success=1
                except Exception as e:
                    job.denied=isinstance(e,PermissionError)
                    self.update_row(job,"Error",str(e));success=0
                if self.selected() is job:self.refresh()
                next_job(index+1,ok+success)
            self.submit(write,finished)
        next_job(0,0)

    def open_saved(self,folder):
        job=self.selected()
        path=job.saved.get(self.printer.get()) if job else None
        if not path:return
        try:
            if not path.is_file():raise FileNotFoundError("The saved copy was moved or removed.")
            if folder:subprocess.Popen(["explorer.exe","/select,",str(path)])
            else:
                exe = core.STUDIO_PROFILES.parent.parent / "flash studio.exe"
                if not exe.is_file():
                    selected = filedialog.askopenfilename(parent=self.root, title="Locate Flash Studio Desktop", filetypes=[("Flash Studio executable", "*.exe")])
                    if not selected:
                        return
                    exe = Path(selected)
                subprocess.Popen([str(exe), str(path)])
        except OSError as e:messagebox.showerror("Could not open the saved project",str(e),parent=self.root)
