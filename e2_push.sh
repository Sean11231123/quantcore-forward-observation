#!/data/data/com.termux/files/usr/bin/bash

cd ~/quantcore-forward-observation || exit

git add .

git commit -m "E2 hourly update"

git push
