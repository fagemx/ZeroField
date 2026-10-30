#!/bin/sh
# Join chained slices into one oner: each slice after the first repeats its predecessor's last frame, so its frame 0 is
# dropped. sh assemble.sh <out.mp4> s1.mp4 s2.mp4 ...
out=$1; shift
inputs=""; filter=""; joins=""; n=0
for f in "$@"; do
  inputs="$inputs -i $f"
  if [ $n -eq 0 ]; then filter="[0:v]setpts=PTS-STARTPTS[v0];"; else filter="$filter[$n:v]trim=start_frame=1,setpts=PTS-STARTPTS[v$n];"; fi
  joins="$joins[v$n]"; n=$((n + 1))
done
ffmpeg -v error -y $inputs -filter_complex "${filter}${joins}concat=n=$n:v=1:a=0[v]" -map "[v]" -c:v libx264 -crf 14 -pix_fmt yuv420p -r 24 "$out" \
  && ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 "$out"
