"""Rain grids in mm (grid_features.Grid interface). raw/pdir/*.npy are int16 mm*100; grid_features.load_pdir* divides by 100 (fixed 31.10.2026).
"""
import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'..'))
import grid_features as gf,numpy as np
def scaled(g,f):
    h=gf.Grid.__new__(gf.Grid); h.__dict__.update(g.__dict__); h.cs=g.cs if f==1 else g.cs*f; h.masks={}; return h
def pdir_window(t0,t1):
    g,cov=gf.load_pdir_window(t0,t1); return g,cov   # already mm
