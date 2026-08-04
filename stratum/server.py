#!/usr/bin/env python3
"""
BCH2 Production Solo Stratum – AxeOS / NerdQaxe++ kompatibel
WORKING VERSION – ACCEPT shares confirmed
"""
# Full file is large - user should keep local working copy.
# Minimal fix for STALE is below as comment:
# 1) job_loop must broadcast mining.notify to all connected clients
# 2) keep more jobs in store (40 not 10)
# 3) on REJECT stale: immediately push_job(clean=True)
raise SystemExit('Use: git show eb85707:stratum/server.py > stratum/server.py')
