import os

conf = """
    location /worksheet-creator/ {
        alias /home/pavel/projects/worksheet-creator/app/frontend/;
        index index.html;
    }

    location /worksheet-api/ {
        rewrite ^/worksheet-api/(.*) /api/$1 break;
        proxy_pass http://127.0.0.1:3005;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
"""

with open('/home/pavel/worksheet-nginx.conf', 'w') as f:
    f.write(conf)

with open('/etc/nginx/sites-available/projects', 'r') as f:
    content = f.read()

if 'location /worksheet-creator/' not in content:
    content = content.replace('location / {', conf + '\n    location / {')
    with open('/home/pavel/projects.conf', 'w') as f:
        f.write(content)
    
    # We will use bash to copy it over because of sudo
    os.system('sudo cp /home/pavel/projects.conf /etc/nginx/sites-available/projects')
    os.system('sudo nginx -t && sudo systemctl reload nginx')
    print("Nginx configuration updated successfully.")
else:
    print("Nginx configuration already contains worksheet-creator.")
