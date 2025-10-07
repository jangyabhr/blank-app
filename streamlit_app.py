import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import cv2
import pandas as pd
from datetime import datetime

# ---------- Model ----------
class Roster:
    def __init__(self):
        self.df = pd.DataFrame(columns=["Admission_No", "Name", "Section"])
        self.index_by_name = {}

    def load_csv(self, path):
        df = pd.read_csv(path, dtype=str).fillna("")
        required = {"Admission_No", "Name"}
        if not required.issubset(set(df.columns)):
            raise ValueError(f"Roster must contain columns: {required}")
        self.df = df
        # Build name -> list of indices (allow duplicate names)
        self.index_by_name = {}
        for idx, row in df.iterrows():
            name = row["Name"]
            self.index_by_name.setdefault(name.lower(), []).append(idx)

    def search(self, query):
        q = query.strip().lower()
        if not q:
            return list(self.df.index)
        mask = self.df["Name"].str.lower().str.contains(q) | self.df["Admission_No"].astype(str).str.contains(q)
        return list(self.df[mask].index)

    def get_display(self, idx):
        r = self.df.loc[idx]
        sec = f" ({r['Section']})" if 'Section' in self.df.columns and r["Section"] else ""
        return f"{r['Name']}{sec}  —  {r['Admission_No']}"

# Face box with assignment
class FaceBox:
    def __init__(self, x, y, w, h, face_id):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.id = face_id
        self.assigned_idx = None  # roster index
        self.rect_obj = None
        self.text_obj = None

    def contains(self, px, py):
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h

# ---------- UI ----------
class App:
    def __init__(self, root):
        self.root = root
        root.title("Tap-on-Face Attendance (Prototype)")
        root.geometry("1100x750")

        self.roster = Roster()
        self.image = None          # PIL Image
        self.tk_image = None       # ImageTk
        self.cv_bgr = None         # OpenCV image (BGR)
        self.photo_path = None
        self.faces = []
        self.scale = 1.0
        self.offset = (0, 0)       # (x_off, y_off) for centering

        # Menu
        menubar = tk.Menu(root)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Open Photo...", command=self.open_photo)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=root.quit)
        menubar.add_cascade(label="File", menu=filemenu)

        rostermenu = tk.Menu(menubar, tearoff=0)
        rostermenu.add_command(label="Load Roster CSV...", command=self.load_roster)
        menubar.add_cascade(label="Roster", menu=rostermenu)

        actionmenu = tk.Menu(menubar, tearoff=0)
        actionmenu.add_command(label="Detect Faces", command=self.detect_faces)
        actionmenu.add_command(label="Save Attendance", command=self.save_attendance)
        menubar.add_cascade(label="Actions", menu=actionmenu)

        root.config(menu=menubar)

        # Canvas for image
        self.canvas = tk.Canvas(root, bg="#111", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Configure>", self.on_resize)

        # Sidebar for present list
        side = tk.Frame(root, width=340, bg="#1e1e1e")
        side.pack(side="right", fill="y")
        tk.Label(side, text="Assigned (Present)", fg="white", bg="#1e1e1e", font=("Segoe UI", 12, "bold")).pack(pady=(10,5))

        self.present_list = tk.Listbox(side, height=20)
        self.present_list.pack(fill="both", expand=True, padx=10, pady=5)

        btn_frame = tk.Frame(side, bg="#1e1e1e")
        btn_frame.pack(fill="x", padx=10, pady=10)
        tk.Button(btn_frame, text="Reassign Selected", command=self.reassign_selected).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Remove Selected", command=self.remove_selected).pack(side="left", padx=5)

        self.status = tk.StringVar(value="Load roster, open a photo, then Actions → Detect Faces.")
        tk.Label(side, textvariable=self.status, wraplength=300, justify="left", fg="#ddd", bg="#1e1e1e").pack(padx=10, pady=10)

    # ---------- Helpers ----------
    def load_roster(self):
        path = filedialog.askopenfilename(title="Select Roster CSV", filetypes=[("CSV Files","*.csv")])
        if not path: return
        try:
            self.roster.load_csv(path)
            self.status.set(f"Loaded roster: {len(self.roster.df)} students.")
        except Exception as e:
            messagebox.showerror("Roster Error", str(e))

    def open_photo(self):
        path = filedialog.askopenfilename(title="Select Photo", filetypes=[("Image Files","*.jpg *.jpeg *.png")])
        if not path: return
        try:
            self.image = Image.open(path).convert("RGB")
            self.photo_path = path
            # Also keep OpenCV version
            import numpy as np
            self.cv_bgr = cv2.cvtColor(np.array(self.image), cv2.COLOR_RGB2BGR)
            self.faces = []
            self.draw_image()
            self.present_list.delete(0, tk.END)
            self.status.set("Photo loaded. Actions → Detect Faces.")
        except Exception as e:
            messagebox.showerror("Photo Error", str(e))

    def on_resize(self, event):
        self.draw_image()

    def draw_image(self):
        if self.image is None:
            self.canvas.delete("all")
            return
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            return
        # Fit image into canvas (letterbox)
        iw, ih = self.image.size
        scale = min(cw / iw, ch / ih)
        new_w, new_h = int(iw * scale), int(ih * scale)
        x_off = (cw - new_w) // 2
        y_off = (ch - new_h) // 2
        disp = self.image.resize((new_w, new_h), Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(disp)
        self.canvas.delete("all")
        self.canvas.create_image(x_off, y_off, anchor="nw", image=self.tk_image)
        self.scale = scale
        self.offset = (x_off, y_off)
        # redraw faces
        for fb in self.faces:
            self.draw_facebox(fb)

    def draw_facebox(self, fb: 'FaceBox'):
        # compute display coords
        x = int(fb.x * self.scale) + self.offset[0]
        y = int(fb.y * self.scale) + self.offset[1]
        w = int(fb.w * self.scale)
        h = int(fb.h * self.scale)
        color = "#2ecc71" if fb.assigned_idx is not None else "#e67e22"
        if fb.rect_obj is not None:
            self.canvas.delete(fb.rect_obj)
        if fb.text_obj is not None:
            self.canvas.delete(fb.text_obj)
        fb.rect_obj = self.canvas.create_rectangle(x, y, x+w, y+h, outline=color, width=3)
        label = f"#{fb.id}" if fb.assigned_idx is None else f"#{fb.id} ✓"
        fb.text_obj = self.canvas.create_text(x+5, y-10, text=label, fill=color, anchor="nw", font=("Segoe UI", 10, "bold"))

    def detect_faces(self):
        if self.cv_bgr is None:
            messagebox.showwarning("No Photo", "Open a photo first.")
            return
        gray = cv2.cvtColor(self.cv_bgr, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40,40))
        self.faces = []
        for i, (x, y, w, h) in enumerate(faces, start=1):
            self.faces.append(FaceBox(int(x), int(y), int(w), int(h), i))
        if not self.faces:
            self.status.set("No faces detected. Try a clearer photo or different angle.")
        else:
            self.status.set(f"Detected {len(self.faces)} faces. Click a box to assign a student.")
        self.draw_image()

    def canvas_to_image_coords(self, px, py):
        # reverse of scaling & offset
        x = (px - self.offset[0]) / self.scale
        y = (py - self.offset[1]) / self.scale
        return int(x), int(y)

    def on_click(self, event):
        if not self.faces:
            return
        ix, iy = self.canvas_to_image_coords(event.x, event.y)
        # find topmost face containing the point
        for fb in reversed(self.faces):
            if fb.contains(ix, iy):
                self.assign_dialog(fb)
                break

    def assign_dialog(self, fb: 'FaceBox'):
        # Dialog with search + listbox to pick a student
        dlg = tk.Toplevel(self.root)
        dlg.title(f"Assign Student to Face #{fb.id}")
        dlg.geometry("480x420")
        tk.Label(dlg, text="Search name or Admission_No:").pack(pady=(10,5))
        qvar = tk.StringVar()
        entry = tk.Entry(dlg, textvariable=qvar)
        entry.pack(fill="x", padx=10)
        listbox = tk.Listbox(dlg)
        listbox.pack(fill="both", expand=True, padx=10, pady=10)

        # populate initial
        def refresh():
            listbox.delete(0, tk.END)
            idxs = self.roster.search(qvar.get())
            for idx in idxs:
                listbox.insert(tk.END, f"{idx}::{self.roster.get_display(idx)}")
        refresh()

        def on_type(*_):
            refresh()
        qvar.trace_add("write", on_type)

        def do_assign():
            sel = listbox.curselection()
            if not sel:
                messagebox.showinfo("Assign", "Select a student from the list.")
                return
            item = listbox.get(sel[0])
            idx = int(item.split("::",1)[0])
            # Check duplicates
            for other in self.faces:
                if other is not fb and other.assigned_idx == idx:
                    if not messagebox.askyesno("Duplicate", "This student is already assigned to another face. Assign again?"):
                        return
            fb.assigned_idx = idx
            self.draw_facebox(fb)
            self.refresh_present_list()
            dlg.destroy()

        btn_frame = tk.Frame(dlg)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="Assign", command=do_assign).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side="left", padx=6)

        entry.focus_set()

    def refresh_present_list(self):
        self.present_list.delete(0, tk.END)
        seen = set()
        for fb in self.faces:
            if fb.assigned_idx is not None and fb.assigned_idx not in seen:
                seen.add(fb.assigned_idx)
                self.present_list.insert(tk.END, self.roster.get_display(fb.assigned_idx))

    def reassign_selected(self):
        sel = self.present_list.curselection()
        if not sel:
            return
        # find matching fb for this display
        disp = self.present_list.get(sel[0])
        # find idx by display text
        idx = None
        for i, row in self.roster.df.iterrows():
            if self.roster.get_display(i) == disp:
                idx = i
                break
        if idx is None:
            return
        # choose a face currently mapped to idx
        for fb in self.faces:
            if fb.assigned_idx == idx:
                self.assign_dialog(fb)
                break

    def remove_selected(self):
        sel = self.present_list.curselection()
        if not sel:
            return
        disp = self.present_list.get(sel[0])
        # remove assignment on the corresponding face
        for fb in self.faces:
            if fb.assigned_idx is not None and self.roster.get_display(fb.assigned_idx) == disp:
                fb.assigned_idx = None
                self.draw_facebox(fb)
                break
        self.refresh_present_list()

    def save_attendance(self):
        if self.roster.df.empty:
            messagebox.showwarning("No Roster", "Load a roster first.")
            return
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base_dir = os.path.abspath(os.path.dirname(__file__))
        out_path = os.path.join(base_dir, f"attendance_{date_str}.xlsx")

        present_idxs = set(fb.assigned_idx for fb in self.faces if fb.assigned_idx is not None)
        status = []
        for i, row in self.roster.df.iterrows():
            status.append({
                "Admission_No": row["Admission_No"],
                "Name": row["Name"],
                "Section": row["Section"] if "Section" in self.roster.df.columns else "",
                "Status": "Present" if i in present_idxs else "Absent",
                "Photo": os.path.basename(self.photo_path) if self.photo_path else "",
                "Saved_At": datetime.now().isoformat(timespec="seconds")
            })
        df = pd.DataFrame(status)
        try:
            df.to_excel(out_path, index=False)
            messagebox.showinfo("Saved", f"Attendance saved:\n{out_path}")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

# ---------- Main ----------
if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
        
