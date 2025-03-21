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
CROCSEEK_PROXY_BASE = os.environ.get('CROCSEEK_PROXY_BASE', 'https://cdn.blockaway.net/_ja/')
ADDITIONAL_PROXY_URL = os.environ.get('ADDITIONAL_PROXY_URL')
SITE_FOLDER = os.environ.get('SITE_FOLDER')

if not all([TARGET_URL, CROCSEEK_PROXY_BASE, SITE_FOLDER]):
    print("Error: Missing required environment variables")
    sys.exit(1)

# Create folders
os.makedirs(SITE_FOLDER, exist_ok=True)
os.makedirs(f"{SITE_FOLDER}/assets", exist_ok=True)
os.makedirs(f"{SITE_FOLDER}/js", exist_ok=True)
os.makedirs(f"{SITE_FOLDER}/css", exist_ok=True)

# Parse the base URL and domain
parsed_url = urlparse(TARGET_URL)
BASE_URL = f"{parsed_url.scheme}://{parsed_url.netloc}"
BASE_DOMAIN = parsed_url.netloc

# Setup additional proxy if provided
proxies = None
if ADDITIONAL_PROXY_URL:
    proxies = {
        'http': ADDITIONAL_PROXY_URL,
        'https': ADDITIONAL_PROXY_URL
    }

# Function to create Crocseek proxy URL
def get_crocseek_url(url):
    encoded_url = urllib.parse.quote(url)
    return f"{CROCSEEK_PROXY_BASE}{encoded_url}"

# Store visited URLs to avoid duplicates
visited_urls = set()
original_to_proxied_url = {}  # Maps original URLs to their proxied versions
js_files = set()
css_files = set()
image_files = set()
other_resources = set()

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

# Function to clean filename
def clean_filename(url):
    # Get the original URL if this is a proxied URL
    original_url = url
    for orig, proxy in original_to_proxied_url.items():
        if proxy == url:
            original_url = orig
            break
            
    parsed = urlparse(original_url)
    path = parsed.path
    
    # Remove trailing slash
    if path.endswith('/'):
        path = path[:-1]
        
    # Default for empty path
    if not path:
        return 'index.html'
        
    # Replace unwanted characters
    filename = re.sub(r'[?&=]', '_', path)
    
    # Ensure the filename has an extension
    if '.' not in os.path.basename(filename):
        filename = os.path.join(filename, 'index.html')
        
    # Remove leading slash
    if filename.startswith('/'):
        filename = filename[1:]
        
    return filename

# Function to save content to file
def save_file(path, content, is_binary=False):
    # Create directory if it doesn't exist
    directory = os.path.dirname(os.path.join(SITE_FOLDER, path))
    os.makedirs(directory, exist_ok=True)
    
    # Save the file
    mode = 'wb' if is_binary else 'w'
    encoding = None if is_binary else 'utf-8'
    
    try:
        with open(os.path.join(SITE_FOLDER, path), mode, encoding=encoding) as f:
            f.write(content)
        print(f"Saved: {path}")
    except Exception as e:
        print(f"Error saving {path}: {e}")

# Function to download static resource
def download_resource(url, resource_type):
    original_url = url
    if url in visited_urls:
        return
        
    visited_urls.add(url)
    
    # Create the proxied URL
    proxied_url = get_crocseek_url(url)
    original_to_proxied_url[original_url] = proxied_url
    
    try:
        response = requests.get(proxied_url, proxies=proxies, timeout=30)
        if response.status_code == 200:
            content_type = response.headers.get('Content-Type', '')
            is_binary = 'text' not in content_type and 'javascript' not in content_type and 'css' not in content_type
            
            # Determine path based on resource type
            parsed = urlparse(original_url)
            path = parsed.path.lstrip('/')
            
            if resource_type == 'js':
                path = f"js/{os.path.basename(path)}"
                js_files.add(original_url)
            elif resource_type == 'css':
                path = f"css/{os.path.basename(path)}"
                css_files.add(original_url)
            elif resource_type == 'image':
                path = f"assets/{os.path.basename(path)}"
                image_files.add(original_url)
            else:
                path = f"assets/{os.path.basename(path)}"
                other_resources.add(original_url)
                
            save_file(path, response.content if is_binary else response.text, is_binary)
            
            # Parse CSS files for additional resources
            if resource_type == 'css':
                css_content = response.text
                # Extract URLs from CSS
                urls = re.findall(r'url\([\'"]?([^\'"]+)[\'"]?\)', css_content)
                for css_url in urls:
                    css_url = normalize_url(css_url)
                    if css_url and css_url not in visited_urls:
                        css_resource_type = 'image' if any(css_url.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']) else 'other'
                        download_resource(css_url, css_resource_type)
                        
    except Exception as e:
        print(f"Error downloading {original_url} via proxy: {e}")

# Function to process HTML page
def process_html(url, html):
    soup = BeautifulSoup(html, 'lxml')
    
    # Process JavaScript files
    for script in soup.find_all('script', src=True):
        js_url = normalize_url(script['src'])
        if js_url and is_same_domain(js_url) and js_url not in visited_urls:
            download_resource(js_url, 'js')
    
    # Process CSS files
    for link in soup.find_all('link', rel='stylesheet'):
        css_url = normalize_url(link.get('href'))
        if css_url and is_same_domain(css_url) and css_url not in visited_urls:
            download_resource(css_url, 'css')
    
    # Process images
    for img in soup.find_all('img', src=True):
        img_url = normalize_url(img['src'])
        if img_url and is_same_domain(img_url) and img_url not in visited_urls:
            download_resource(img_url, 'image')
    
    # Process internal links
    links = []
    for a in soup.find_all('a', href=True):
        link_url = normalize_url(a['href'])
        if link_url and is_same_domain(link_url) and link_url not in visited_urls:
            links.append(link_url)
            
    return links

# Main function for dynamic content scraping
async def scrape_with_browser():
    print(f"Starting to scrape {TARGET_URL} through Crocseek Proxy {CROCSEEK_PROXY_BASE}")
    
    # Create the proxied URL for the target
    proxied_target_url = get_crocseek_url(TARGET_URL)
    original_to_proxied_url[TARGET_URL] = proxied_target_url
    
    print(f"Proxied URL: {proxied_target_url}")
    
    # Launch browser with additional proxy if provided
    browser_args = [
        '--no-sandbox',
        '--disable-setuid-sandbox'
    ]
    
    if ADDITIONAL_PROXY_URL:
        browser_args.append(f'--proxy-server={ADDITIONAL_PROXY_URL.replace("http://", "").replace("https://", "")}')
    
    browser = await launch(
        headless=True,
        args=browser_args
    )
    
    try:
        # Create a queue for URLs to scrape
        queue = [TARGET_URL]  # Store original URLs in queue
        
        while queue and len(visited_urls) < 1000:  # Limit to prevent infinite loops
            current_url = queue.pop(0)
            
            if current_url in visited_urls:
                continue
                
            # Get or create proxied URL
            if current_url in original_to_proxied_url:
                current_proxied_url = original_to_proxied_url[current_url]
            else:
                current_proxied_url = get_crocseek_url(current_url)
                original_to_proxied_url[current_url] = current_proxied_url
            
            print(f"Scraping: {current_url}")
            print(f"Via Proxy: {current_proxied_url}")
            visited_urls.add(current_url)
            
            try:
                # Open a new page
                page = await browser.newPage()
                
                # Set viewport
                await page.setViewport({'width': 1920, 'height': 1080})
                
                # Navigate to URL through proxy
                response = await page.goto(current_proxied_url, {
                    'waitUntil': 'networkidle0',
                    'timeout': 60000
                })
                
                # Get page content
                html = await page.content()
                
                # Save HTML
                filename = clean_filename(current_url)
                save_file(filename, html)
                
                # Process HTML for additional resources
                new_links = process_html(current_url, html)
                queue.extend([link for link in new_links if link not in visited_urls])
                
                # Get all scripts loaded on the page
                scripts = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('script')).map(s => s.src);
                }''')
                
                for script in scripts:
                    if script and script not in js_files:
                        # Convert back to original domain if it's a proxied URL
                        if CROCSEEK_PROXY_BASE in script:
                            # Extract the original URL from the proxied URL
                            original_script = urllib.parse.unquote(script.replace(CROCSEEK_PROXY_BASE, ''))
                            if is_same_domain(original_script) and original_script not in visited_urls:
                                download_resource(original_script, 'js')
                        elif is_same_domain(script) and script not in visited_urls:
                            download_resource(script, 'js')
                
                # Close page
                await page.close()
                
            except Exception as e:
                print(f"Error processing {current_url}: {e}")
                
            # Delay to be nice to the server
            await asyncio.sleep(1)
    
    finally:
        # Close browser
        await browser.close()
        
        # Save metadata
        metadata = {
            'base_url': TARGET_URL,
            'crocseek_proxy_base': CROCSEEK_PROXY_BASE,
            'scraped_pages': list(visited_urls),
            'original_to_proxied_mapping': {k: v for k, v in original_to_proxied_url.items()},
            'js_files': list(js_files),
            'css_files': list(css_files),
            'image_files': list(image_files),
            'other_resources': list(other_resources)
        }
        
        save_file('metadata.json', json.dumps(metadata, indent=2))
        print(f"Scraping completed. Processed {len(visited_urls)} URLs.")

# Run the main function
if __name__ == "__main__":
    asyncio.run(scrape_with_browser())
