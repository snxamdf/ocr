tail -f logs/`ls -lhort logs|awk '{print $8}'|tail -n 1`