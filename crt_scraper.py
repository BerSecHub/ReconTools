#!/usr/bin/env python3

import argparse
import os
import sys
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote


def setup_argparse():
    parser = argparse.ArgumentParser(
        description='Scrape certificate transparency logs from crt.sh and extract unique domains',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('-d', '--domain', required=True, help='Target domain to search for (e.g., example.com)')
    parser.add_argument('-o', '--output', default='domains.txt', help='Output file path (default: domains.txt)')
    parser.add_argument('-w', '--wildcard', action='store_true', help='Include wildcard search (%%.domain.com)')
    parser.add_argument('-e', '--exclude-expired', action='store_true', help='Exclude expired certificates')
    parser.add_argument('-j', '--json', action='store_true', help='Use JSON API instead of HTML scraping (faster)')
    parser.add_argument('-t', '--timeout', type=int, default=30, help='Request timeout in seconds (default: 30)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')
    
    return parser.parse_args()


def get_domains_from_html(domain, include_wildcard, exclude_expired, timeout, verbose):
    """Scrape domains from crt.sh HTML page"""
    search_domain = f'%.{domain}' if include_wildcard else domain
    url = f'https://crt.sh/?q={quote(search_domain)}'
    
    if exclude_expired:
        url += '&exclude=expired'
    
    if verbose:
        print(f'Querying: {url}')
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
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
                if name_data:
                    # Split by newlines or commas and process each domain
                    for subdomain in name_data.replace('\n', ',').split(','):
                        subdomain = subdomain.strip()
                        if '.' in subdomain and domain in subdomain:
                            # Clean up the domain (remove wildcards, spaces, etc.)
                            clean_domain = subdomain.replace('*.', '').replace('.', '', 1) if subdomain.startswith('*.') else subdomain
                            clean_domain = clean_domain.strip()
                            if clean_domain and '.' in clean_domain and domain in clean_domain:
                                domains.add(clean_domain)
        
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
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        data = response.json()
        domains = set()
        
        for entry in data:
            # The JSON API uses 'name_value' for the domain field
            name_value = entry.get('name_value', '')
            if name_value:
                # Split by newlines or commas and process each domain
                for subdomain in name_value.replace('\n', ',').split(','):
                    subdomain = subdomain.strip()
                    if '.' in subdomain and domain in subdomain:
                        # Clean up the domain (remove wildcards, spaces, etc.)
                        clean_domain = subdomain.replace('*.', '').replace('.', '', 1) if subdomain.startswith('*.') else subdomain
                        clean_domain = clean_domain.strip()
                        if clean_domain and '.' in clean_domain and domain in clean_domain:
                            domains.add(clean_domain)
        
        return sorted(list(domains))
    
    except (requests.RequestException, json.JSONDecodeError) as e:
        print(f'Error querying crt.sh JSON API: {e}', file=sys.stderr)
        # Fall back to HTML scraping if JSON fails
        if verbose:
            print('Falling back to HTML scraping method...')
        return get_domains_from_html(domain, include_wildcard, exclude_expired, timeout, verbose)


def main():
    args = setup_argparse()
    
    print(f'Starting crt.sh scraper for domain: {args.domain}')
    
    # Get domains using either JSON API or HTML scraping
    if args.json:
        domains = get_domains_from_json(args.domain, args.wildcard, args.exclude_expired, args.timeout, args.verbose)
    else:
        domains = get_domains_from_html(args.domain, args.wildcard, args.exclude_expired, args.timeout, args.verbose)
    
    if not domains:
        print('No domains found.')
        return
    
    # Write to output file
    output_path = os.path.abspath(args.output)
    with open(output_path, 'w') as f:
        f.write('\n'.join(domains))
    
    print(f'Found {len(domains)} unique domains.')
    print(f'Results saved to: {output_path}')
    
    if args.verbose:
        print('\nDomains found:')
        for domain in domains:
            print(f'- {domain}')


if __name__ == '__main__':
    main()
