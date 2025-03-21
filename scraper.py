#!/usr/bin/env python3
# scraper.py

import os
import sys
import re
import json
import time
import urllib.parse
import requests
from bs4 import BeautifulSoup
import asyncio
from pyppeteer import launch
import aiohttp
import ssl
import certifi
from urllib.parse import urljoin, urlparse

# Get environment variables
TARGET_URL = os.environ.get('TARGET_URL')
PROXY_URL = os.environ.get('PROXY_URL')
SITE_FOLDER = os.environ.get('SITE_FOLDER', 'docs')

if not TARGET_URL:
    print("Error: Missing TARGET_URL environment variable")
    sys.exit(1)

# Create folders
os.makedirs(SITE_FOLDER, exist_ok=True)

# Parse the base URL and domain
parsed_url = urlparse(TARGET_URL)
BASE_URL = f"{parsed_url.scheme}://{parsed_url.netloc}"
BASE_DOMAIN = parsed_url.netloc

# Setup proxy if provided
proxies = None
if PROXY_URL:
    proxies = {
        'http': PROXY_URL,
        'https': PROXY_URL
    }

# Store visited URLs to avoid duplicates
visited_urls = set()
downloaded_files = {}  # Maps original URLs to local file paths

# Function to normalize URL
def normalize_url(url):
    if not url:
        return None
        
    # Remove fragments
    url = url.split('#')[0]
    
    # Handle relative URLs
    if not url.startswith('http'):
        url = urljoin(BASE_URL, url)
        
    return url

# Function to check if URL is from the same domain
def is_same_domain(url):
    if not url:
        return False
        
    parsed = urlparse(url)
    return parsed.netloc == BASE_DOMAIN or not parsed.netloc

# Function to generate local path for a URL
def get_local_path(url):
    parsed = urlparse(url)
    path = parsed.path
    
    # Remove trailing slash
    if path.endswith('/'):
        path = path[:-1]
        
    # Default for empty path
    if not path:
        return 'index.html'
        
    # Add index.html for directory paths
    if '.' not in os.path.basename(path):
        if not path.endswith('/'):
            path = path + '/'
        path = path + 'index.html'
        
    # Remove leading slash
    if path.startswith('/'):
        path = path[1:]
        
    return path

# Function to save content to file
def save_file(path, content, is_binary=False):
    full_path = os.path.join(SITE_FOLDER, path)
    
    # Create directory if it doesn't exist
    directory = os.path.dirname(full_path)
    os.makedirs(directory, exist_ok=True)
    
    # Save the file
    mode = 'wb' if is_binary else 'w'
    encoding = None if is_binary else 'utf-8'
    
    try:
        with open(full_path, mode, encoding=encoding) as f:
            f.write(content)
        print(f"Saved: {path}")
        return True
    except Exception as e:
        print(f"Error saving {path}: {e}")
        return False

# Process HTML to keep original URLs
def process_html_preserve_urls(html, base_url):
    soup = BeautifulSoup(html, 'lxml')
    
    # Find all links to be processed later
    links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        url = normalize_url(href)
        if url and is_same_domain(url) and url not in visited_urls:
            links.append(url)
            
    # Leave all URLs as they are - don't modify them
    # This preserves the original site structure
            
    return str(soup), links

# Main function for dynamic content scraping
async def scrape_with_browser():
    print(f"Starting to scrape {TARGET_URL}")
    
    # Launch browser
    browser_args = [
        '--no-sandbox',
        '--disable-setuid-sandbox',
    ]
    
    if PROXY_URL:
        browser_args.append(f'--proxy-server={PROXY_URL.replace("http://", "").replace("https://", "")}')
    
    browser = await launch(
        headless=True,
        args=browser_args
    )
    
    try:
        # Create a queue for URLs to scrape
        queue = [TARGET_URL]
        
        while queue and len(visited_urls) < 1000:  # Limit to prevent infinite loops
            current_url = queue.pop(0)
            
            if current_url in visited_urls:
                continue
                
            print(f"Scraping: {current_url}")
            visited_urls.add(current_url)
            
            try:
                # Open a new page
                page = await browser.newPage()
                
                # Set viewport
                await page.setViewport({'width': 1920, 'height': 1080})
                
                # Navigate to URL
                response = await page.goto(current_url, {
                    'waitUntil': 'networkidle0',
                    'timeout': 60000
                })
                
                # Get page content
                html = await page.content()
                
                # Process HTML - keep original URLs
                processed_html, new_links = process_html_preserve_urls(html, current_url)
                
                # Save HTML
                local_path = get_local_path(current_url)
                if save_file(local_path, processed_html):
                    downloaded_files[current_url] = local_path
                
                # Add new links to queue
                queue.extend([link for link in new_links if link not in visited_urls])
                
                # Save screenshots for reference
                screenshot_path = local_path.rsplit('.', 1)[0] + '.png'
                await page.screenshot({'path': os.path.join(SITE_FOLDER, screenshot_path), 'fullPage': True})
                
                # Wait for resources to load
                await asyncio.sleep(1)
                
                # Close page
                await page.close()
                
            except Exception as e:
                print(f"Error processing {current_url}: {e}")
                
            # Delay to be nice to the server
            await asyncio.sleep(1)
    
    finally:
        # Close browser
        await browser.close()
        
        # Create a GitHub Pages index file
        create_index_page()
        
        # Save metadata
        metadata = {
            'base_url': TARGET_URL,
            'scraped_pages': list(visited_urls),
            'downloaded_files': downloaded_files
        }
        
        save_file('metadata.json', json.dumps(metadata, indent=2))
        print(f"Scraping completed. Processed {len(visited_urls)} URLs.")

# Create an index.html page for GitHub Pages
def create_index_page():
    index_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Website Archive of {BASE_DOMAIN}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }}
        h1 {{
            color: #333;
            border-bottom: 1px solid #eee;
            padding-bottom: 10px;
        }}
        ul {{
            list-style-type: none;
            padding: 0;
        }}
        li {{
            margin-bottom: 10px;
            padding: 10px;
            background-color: #f9f9f9;
            border-radius: 5px;
        }}
        a {{
            color: #0366d6;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .note {{
            background-color: #fffbe6;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 20px;
            border-left: 4px solid #ffe58f;
        }}
    </style>
</head>
<body>
    <h1>Website Archive of {BASE_DOMAIN}</h1>
    <div class="note">
        <p>This is an archived version of {TARGET_URL}</p>
        <p>Archived on: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p>Note: All links point to the original website. This is a mirror for reference purposes only.</p>
    </div>
    <h2>Archived Pages:</h2>
    <ul>
"""
    
    # Add links to all downloaded pages
    for url, local_path in sorted(downloaded_files.items()):
        index_content += f'        <li><a href="{local_path}">{url}</a></li>\n'
    
    index_content += """    </ul>
</body>
</html>
"""
    
    save_file('index.html', index_content)
    print("Created index.html for GitHub Pages")

# Run the main function
if __name__ == "__main__":
    asyncio.run(scrape_with_browser())
