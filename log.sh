tail -f logs/`ls logs -rot|awk '{print $8}'|tail -n 1`