#!/bin/bash
# Open port 8000 on Oracle Cloud VM
# Oracle uses iptables by default
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save
echo "Port 8000 opened"
