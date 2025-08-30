#!/usr/bin/env python3

import argparse
import os
import sys
import json
import re
import requests
import concurrent.futures
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse


def setup_argparse():
    parser = argparse.ArgumentParser(
        description='Scrape certificate transparency logs from crt.sh and extract unique domains',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('-d', '--domain', required=True, help='Target domain to search for (e.g., example.com)')
    parser.add_argument('-o', '--output', help='Output file path (default: [domain]_subdomains.txt)')
    parser.add_argument('-w', '--wildcard', action='store_true', help='Include wildcard search (%%.domain.com)')
    parser.add_argument('-e', '--exclude-expired', action='store_true', help='Exclude expired certificates')
    parser.add_argument('-j', '--json', action='store_true', help='Use JSON API instead of HTML scraping (faster)')
    parser.add_argument('-t', '--timeout', type=int, default=30, help='Request timeout in seconds (default: 30)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('-c', '--check', action='store_true', help='Check HTTP status of each domain')
    parser.add_argument('-m', '--max-workers', type=int, default=10, help='Maximum number of concurrent workers for status checking (default: 10)')
    parser.add_argument('--no-color', action='store_true', help='Disable colored output')
    
    args = parser.parse_args()
    
    # Set default output filename based on domain name if not specified
    if not args.output:
        args.output = f"{args.domain}_subdomains.txt"
    
    return args


def get_domains_from_html(domain, include_wildcard, exclude_expired, timeout, verbose):
    """Scrape domains from crt.sh HTML page"""
    search_domain = f'%.{domain}' if include_wildcard else domain
    url = f'https://crt.sh/?q={quote(search_domain)}'
    
    if exclude_expired:
        url += '&exclude=expired'
    
    if verbose:
        print(f'Querying: {url}')
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        domains = set()
        
        # Find the table rows and extract domain data from the 6th column
        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) >= 6:
                # Extract domain name data from the 6th column
                name_data = cells[5].get_text().strip()
                if name_data and domain in name_data:
                    # Split by multiple separators and also split concatenated domains
                    subdomains = re.split(r'[\n,\s]+', name_data)
                    for subdomain in subdomains:
                        subdomain = subdomain.strip()
                        if subdomain.startswith('*.'):
                            subdomain = subdomain[2:]
                        
                        # Handle concatenated domains like "ebok.aquanet.plwww.ebok.aquanet.pl"
                        if subdomain.count(domain) > 1:
                            # Split on the domain pattern
                            parts = subdomain.split(domain)
                            for i, part in enumerate(parts[:-1]):  # Skip the last empty part
                                reconstructed = part + domain
                                if reconstructed and '.' in reconstructed:
                                    domains.add(reconstructed)
                        elif subdomain and '.' in subdomain and domain in subdomain:
                            domains.add(subdomain)
        
        return sorted(list(domains))
    
    except requests.RequestException as e:
        print(f'Error querying crt.sh: {e}', file=sys.stderr)
        return []


def get_domains_from_json(domain, include_wildcard, exclude_expired, timeout, verbose):
    """Get domains from crt.sh JSON API (faster method)"""
    search_domain = f'%.{domain}' if include_wildcard else domain
    url = f'https://crt.sh/?q={quote(search_domain)}&output=json'
    
    if exclude_expired:
        url += '&exclude=expired'
    
    if verbose:
        print(f'Querying JSON API: {url}')
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        data = response.json()
        domains = set()
        
        for entry in data:
            # The JSON API uses 'name_value' for the domain field
            name_value = entry.get('name_value', '')
            if name_value and domain in name_value:
                # Split by multiple separators and also split concatenated domains
                subdomains = re.split(r'[\n,\s]+', name_value)
                for subdomain in subdomains:
                    subdomain = subdomain.strip()
                    if subdomain.startswith('*.'):
                        subdomain = subdomain[2:]
                    
                    # Handle concatenated domains like "ebok.aquanet.plwww.ebok.aquanet.pl"
                    if subdomain.count(domain) > 1:
                        # Split on the domain pattern
                        parts = subdomain.split(domain)
                        for i, part in enumerate(parts[:-1]):  # Skip the last empty part
                            reconstructed = part + domain
                            if reconstructed and '.' in reconstructed:
                                domains.add(reconstructed)
                    elif subdomain and '.' in subdomain and domain in subdomain:
                        domains.add(subdomain)
        
        return sorted(list(domains))
    
    except (requests.RequestException, json.JSONDecodeError) as e:
        print(f'Error querying crt.sh JSON API: {e}', file=sys.stderr)
        # Fall back to HTML scraping if JSON fails
        if verbose:
            print('Falling back to HTML scraping method...')
        return get_domains_from_html(domain, include_wildcard, exclude_expired, timeout, verbose)


# Define color codes
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def check_domain_status(domain, timeout=5):
    """Check HTTP status for a domain"""
    for protocol in ['https', 'http']:
        url = f"{protocol}://{domain}"
        try:
            response = requests.head(url, timeout=timeout, allow_redirects=True)
            return {
                'domain': domain,
                'url': url,
                'status_code': response.status_code,
                'redirected': response.url != url
            }
        except requests.RequestException:
            if protocol == 'http':
                return {
                    'domain': domain,
                    'url': url,
                    'status_code': 0,
                    'error': True
                }
    
    return {'domain': domain, 'status_code': 0, 'error': True}

def check_domains_status(domains, max_workers=10, timeout=5):
    """Check HTTP status for multiple domains concurrently"""
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_domain = {executor.submit(check_domain_status, domain, timeout): domain for domain in domains}
        for future in concurrent.futures.as_completed(future_to_domain):
            results.append(future.result())
    return results

def get_status_color(status_code):
    """Return color code based on HTTP status"""
    if status_code == 0:
        return Colors.RED  # Error/timeout
    elif 200 <= status_code < 300:
        return Colors.GREEN
    elif 300 <= status_code < 400:
        return Colors.BLUE
    elif 400 <= status_code < 500:
        return Colors.YELLOW
    elif status_code >= 500:
        return Colors.RED
    return Colors.RESET

def print_status_results(results, use_color=True):
    """Print domain check results with optional coloring"""
    for result in sorted(results, key=lambda x: x['domain']):
        domain = result['domain']
        status = result['status_code']
        
        if status == 0:
            status_text = "ERROR"
        else:
            status_text = str(status)
        
        if use_color:
            color = get_status_color(status)
            redirected = result.get('redirected', False)
            redirect_info = f" → {Colors.CYAN}{urlparse(result['url']).netloc}{Colors.RESET}" if redirected else ""
            print(f"{domain} - {color}{status_text}{Colors.RESET}{redirect_info}")
        else:
            print(f"{domain} - {status_text}")

def main():
    args = setup_argparse()
    
    # Basic domain validation
    if not args.domain or '.' not in args.domain:
        print(f'Error: Invalid domain format: {args.domain}', file=sys.stderr)
        sys.exit(1)
    
    print(f'Starting crt.sh scraper for domain: {args.domain}')
    
    # Get domains using either JSON API or HTML scraping
    if args.json:
        domains = get_domains_from_json(args.domain, args.wildcard, args.exclude_expired, args.timeout, args.verbose)
    else:
        domains = get_domains_from_html(args.domain, args.wildcard, args.exclude_expired, args.timeout, args.verbose)
    
    if not domains:
        print('No domains found.')
        return
    
    # Write to output file (clean list format)
    output_path = os.path.abspath(args.output)
    with open(output_path, 'w') as f:
        f.write('\n'.join(domains))
    
    print(f'Found {len(domains)} unique domains.')
    print(f'Results saved to: {output_path}')
    
    # Check HTTP status if requested
    if args.check:
        print("\nChecking HTTP status for each domain...")
        results = check_domains_status(domains, args.max_workers, args.timeout)
        print("\nDomain Status Results:")
        print_status_results(results, not args.no_color)
    elif args.verbose:
        print('\nDomains found:')
        for domain in domains:
            print(f'- {domain}')


if __name__ == '__main__':
    main()