# 3. Install Python and required packages in all containers
for container in ubuntu1 ubuntu2 ubuntu3; do
    echo "Setting up $container..."
    podman exec $container apt-get update
    podman exec $container apt-get install -y python3 python3-pip
    podman exec $container pip3 install ipaddress
done

# 4. Copy files to respective containers
# First, create necessary directories
for container in ubuntu1 ubuntu2 ubuntu3; do
    podman exec $container mkdir -p /app
done

# Copy handler.py and node_base.py to ubuntu1
podman cp ./handler.py ubuntu1:/app/
podman cp ./node_base.py ubuntu1:/app/

# Copy node.py and node_base.py to ubuntu2 and ubuntu3
for container in ubuntu2 ubuntu3; do
    podman cp ./node.py $container:/app/
    podman cp ./node_base.py $container:/app/
done

# 5. Modify configuration files for each component
# Update handler.py configuration on ubuntu1
podman exec ubuntu1 sed -i 's/192.168.1.1/10.100.0.1/g' /app/handler.py
podman exec ubuntu1 sed -i 's/192.168.1.2/host.containers.internal/g' /app/handler.py

# Update node_base.py on all containers to use correct handler IP
for container in ubuntu1 ubuntu2 ubuntu3; do
    podman exec $container sed -i 's/192.168.1.1/10.100.0.1/g' /app/node_base.py
done
