#!/bin/bash

for port in {5001..5011}
do
    gnome-terminal --tab -- bash -c "python node.py $port; exec bash"
done
