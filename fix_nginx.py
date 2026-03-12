import re
import os

with open('/etc/nginx/sites-available/projects', 'r') as f:
    text = f.read()

# Remove the include line
text = text.replace('    include /tmp/worksheet-nginx.conf;\n', '')

# Remove all occurrences of location /worksheet-creator/ and /worksheet-api/ blocks
pattern = re.compile(r'\s*location /worksheet-creator/ \{.*?\n\s*\}\n', re.DOTALL)
text = pattern.sub('', text)

pattern2 = re.compile(r'\s*location /worksheet-api/ \{.*?\n\s*\}\n', re.DOTALL)
text = text.replace('    location /worksheet-api/ {\n        rewrite ^/worksheet-api/(.*) /api/$1 break;\n        proxy_pass http://127.0.0.1:3005;\n        proxy_set_header Host $host;\n        proxy_set_header X-Real-IP $remote_addr;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n        proxy_set_header X-Forwarded-Proto $scheme;\n    }\n', '')

pattern3 = re.compile(r'\s*location /worksheet-api/ \{.*?\n\s*\}\n', re.DOTALL)
text = pattern3.sub('', text)

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

text = text.replace('    location / {', conf + '\n    location / {')

with open('/home/pavel/clean_projects.conf', 'w') as f:
    f.write(text)

os.system('sudo cp /home/pavel/clean_projects.conf /etc/nginx/sites-available/projects')
os.system('sudo nginx -t && sudo systemctl reload nginx')
