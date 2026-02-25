#!/usr/bin/env python3
"""Historical Data Backfill CLI Tool for CVM Credit Market Data.

This tool downloads historical CVM data with support for:
- Resume capability
- Parallel downloads
- Progress tracking
- Error handling with retries
- Incremental updates
"""

import argparse
import hashlib
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from tqdm import tqdm

from backfill_config import (
    BackfillConfig,
    EntityConfig,
    EntityType,
    DocumentType,
    Frequency,
    generate_periods,
    get_current_period,
)
from progress_tracker import ProgressTracker, DownloadStatus

class CVMBackfiller:
    """Main backfill orchestrator for CVM data."""
    
    def __init__(self, max_workers: int = None, verbose: bool = False):
        """Initialize backfiller.
        
        Args:
            max_workers: Maximum number of parallel download workers
            verbose: Enable verbose logging
        """
        self.max_workers = max_workers or BackfillConfig.MAX_WORKERS
        self.verbose = verbose
        self.progress_tracker = ProgressTracker()
        
        # Setup logging
        self._setup_logging()
        
        # Initialize directories
        BackfillConfig.initialize_directories()
        
        self.logger.info("CVMBackfiller initialized")
    
    def _setup_logging(self):
        """Configure logging."""
        log_level = logging.DEBUG if self.verbose else logging.INFO
        
        # Create logger
        self.logger = logging.getLogger("CVMBackfiller")
        self.logger.setLevel(log_level)
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_format)
        self.logger.addHandler(console_handler)
        
        # File handler
        log_file = BackfillConfig.LOG_DIR / f"backfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(console_format)
        self.logger.addHandler(file_handler)
    
    def _download_file(self, url: str, file_path: Path, period: str, 
                       config: EntityConfig) -> Tuple[bool, Optional[str], Optional[str]]:
        """Download a single file with retry logic.
        
        Args:
            url: Download URL
            file_path: Local file path
            period: Period identifier
            config: Entity configuration
        
        Returns:
            Tuple of (success, error_message, checksum)
        """
        for attempt in range(BackfillConfig.MAX_RETRIES):
            try:
                self.logger.debug(f"Downloading {url} (attempt {attempt + 1}/{BackfillConfig.MAX_RETRIES})")
                
                response = requests.get(
                    url,
                    timeout=BackfillConfig.REQUEST_TIMEOUT,
                    stream=True
                )
                response.raise_for_status()
                
                # Download with progress
                total_size = int(response.headers.get('content-length', 0))
                
                # Write file and calculate checksum
                hasher = hashlib.sha256()
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            hasher.update(chunk)
                
                checksum = hasher.hexdigest()
                
                self.logger.debug(f"Successfully downloaded {file_path}")
                return True, None, checksum
            
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    # File doesn't exist on server - not an error
                    self.logger.debug(f"File not found (404): {url}")
                    return False, "File not found (404)", None
                else:
                    error_msg = f"HTTP error {e.response.status_code}: {str(e)}"
                    self.logger.warning(f"{error_msg} - {url}")
            
            except requests.exceptions.RequestException as e:
                error_msg = f"Request error: {str(e)}"
                self.logger.warning(f"{error_msg} - {url}")
            
            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
                self.logger.error(f"{error_msg} - {url}", exc_info=True)
            
            # Retry delay
            if attempt < BackfillConfig.MAX_RETRIES - 1:
                time.sleep(BackfillConfig.RETRY_DELAY * (attempt + 1))
        
        return False, error_msg, None
    
    def _process_period(self, period: str, config: EntityConfig, 
                        skip_existing: bool = True) -> Dict:
        """Process a single period download.
        
        Args:
            period: Period identifier (YYYYMM)
            config: Entity configuration
            skip_existing: Skip if already downloaded successfully
        
        Returns:
            Download result dictionary
        """
        # Check if already downloaded
        if skip_existing:
            status = self.progress_tracker.get_download_status(
                config.entity_type.value,
                config.doc_type.value,
                period
            )
            if status == DownloadStatus.COMPLETED:
                return {
                    'period': period,
                    'status': 'skipped',
                    'message': 'Already downloaded'
                }
        
        # Generate URL and file path
        url = config.get_url(period)
        file_path = config.get_file_path(BackfillConfig.BASE_DIR, period)
        
        # Mark as in progress
        self.progress_tracker.mark_in_progress(
            config.entity_type.value,
            config.doc_type.value,
            period
        )
        
        # Download file
        success, error_msg, checksum = self._download_file(url, file_path, period, config)
        
        if success:
            # Mark as completed
            self.progress_tracker.mark_completed(
                config.entity_type.value,
                config.doc_type.value,
                period,
                str(file_path),
                checksum
            )
            return {
                'period': period,
                'status': 'success',
                'file_path': str(file_path),
                'checksum': checksum
            }
        else:
            # Mark as failed
            self.progress_tracker.mark_failed(
                config.entity_type.value,
                config.doc_type.value,
                period,
                error_msg or "Unknown error"
            )
            return {
                'period': period,
                'status': 'failed',
                'error': error_msg
            }
    
    def backfill(self, config: EntityConfig, start_date: str, end_date: str, 
                 skip_existing: bool = True) -> Dict:
        """Backfill data for a specific configuration.
        
        Args:
            config: Entity configuration
            start_date: Start date in YYYYMM format
            end_date: End date in YYYYMM format
            skip_existing: Skip already downloaded files
        
        Returns:
            Summary dictionary with results
        """
        self.logger.info(
            f"Starting backfill for {config.entity_type.value}/{config.doc_type.value} "
            f"from {start_date} to {end_date}"
        )
        
        # Generate periods
        periods = generate_periods(start_date, end_date, config.frequency)
        self.logger.info(f"Generated {len(periods)} periods to process")
        
        # Track results
        results = {
            'total': len(periods),
            'success': 0,
            'failed': 0,
            'skipped': 0,
            'details': []
        }
        
        # Process downloads in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_period = {
                executor.submit(self._process_period, period, config, skip_existing): period
                for period in periods
            }
            
            # Process completed tasks with progress bar
            with tqdm(total=len(periods), desc=f"{config.entity_type.value}/{config.doc_type.value}") as pbar:
                for future in as_completed(future_to_period):
                    period = future_to_period[future]
                    try:
                        result = future.result()
                        results['details'].append(result)
                        
                        if result['status'] == 'success':
                            results['success'] += 1
                        elif result['status'] == 'failed':
                            results['failed'] += 1
                        elif result['status'] == 'skipped':
                            results['skipped'] += 1
                        
                        pbar.update(1)
                    
                    except Exception as e:
                        self.logger.error(f"Error processing period {period}: {str(e)}", exc_info=True)
                        results['failed'] += 1
                        results['details'].append({
                            'period': period,
                            'status': 'failed',
                            'error': str(e)
                        })
                        pbar.update(1)
        
        self.logger.info(
            f"Backfill completed: {results['success']} success, "
            f"{results['failed']} failed, {results['skipped']} skipped"
        )
        
        return results
    
    def backfill_all(self, start_date: Optional[str] = None, 
                     end_date: Optional[str] = None) -> Dict:
        """Backfill all configured entities.
        
        Args:
            start_date: Override start date (YYYYMM)
            end_date: Override end date (YYYYMM)
        
        Returns:
            Combined summary dictionary
        """
        all_results = {}
        
        for key, config in BackfillConfig.ENTITY_CONFIGS.items():
            # Use config start date if not overridden
            effective_start = start_date or config.start_date
            effective_end = end_date or get_current_period(config.frequency)
            
            results = self.backfill(config, effective_start, effective_end)
            all_results[key] = results
        
        return all_results
    
    def update(self, config: EntityConfig) -> Dict:
        """Incremental update - fetch only new data since last download.
        
        Args:
            config: Entity configuration
        
        Returns:
            Summary dictionary with results
        """
        # Get last downloaded period
        last_period = self.progress_tracker.get_last_completed_period(
            config.entity_type.value,
            config.doc_type.value
        )
        
        if last_period:
            # Start from next period after last downloaded
            year = int(last_period[:4])
            month = int(last_period[4:6])
            
            if config.frequency == Frequency.MONTHLY:
                month += 1
                if month > 12:
                    month = 1
                    year += 1
            elif config.frequency == Frequency.QUADRIMESTRAL:
                if month == 1:
                    month = 5
                elif month == 5:
                    month = 9
                else:
                    month = 1
                    year += 1
            
            start_date = f"{year}{month:02d}"
        else:
            # No previous downloads, use config start date
            start_date = config.start_date
        
        end_date = get_current_period(config.frequency)
        
        self.logger.info(f"Incremental update from {start_date} to {end_date}")
        
        return self.backfill(config, start_date, end_date, skip_existing=True)
    
    def get_summary(self) -> Dict:
        """Get overall download summary.
        
        Returns:
            Summary statistics
        """
        return self.progress_tracker.get_summary()

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Historical Data Backfill Tool for CVM Credit Market Data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:

# Download all FIDC monthly reports from 2019 to 2024
  python backfill.py --entity FIDC --doc-type INF_MENSAL --start-date 201901 --end-date 202412

# Download everything
  python backfill.py --all

# Incremental update for SECURIT
  python backfill.py --entity SECURIT --update

# Update specific document type
  python backfill.py --entity SECURIT --doc-type CRA_MENSAL --update

# Get download summary
  python backfill.py --summary
        """
    )
    
    # Entity and document type selection
    parser.add_argument(
        '--entity',
        type=str,
        choices=[e.value for e in EntityType],
        help='Entity type to download'
    )
    parser.add_argument(
        '--doc-type',
        type=str,
        choices=[d.value for d in DocumentType],
        help='Document type to download'
    )
    
    # Date range
    parser.add_argument(
        '--start-date',
        type=str,
        help='Start date in YYYYMM format (e.g., 201901)'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        help='End date in YYYYMM format (e.g., 202412)'
    )
    
    # Operations
    parser.add_argument(
        '--all',
        action='store_true',
        help='Download all configured entities'
    )
    parser.add_argument(
        '--update',
        action='store_true',
        help='Incremental update (fetch only new data)'
    )
    parser.add_argument(
        '--summary',
        action='store_true',
        help='Show download summary and exit'
    )
    
    # Configuration
    parser.add_argument(
        '--workers',
        type=int,
        default=BackfillConfig.MAX_WORKERS,
        help=f'Number of parallel workers (default: {BackfillConfig.MAX_WORKERS})'
    )
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        default=True,
        help='Skip already downloaded files (default: True)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Create backfiller
    backfiller = CVMBackfiller(max_workers=args.workers, verbose=args.verbose)
    
    # Show summary
    if args.summary:
        summary = backfiller.get_summary()
        print("\n=== Download Summary ===")
        for entity, stats in summary.items():
            print(f"\n{entity}:")
            print(f"  Total: {stats['total']}")
            print(f"  Completed: {stats['completed']}")
            print(f"  Failed: {stats['failed']}")
            print(f"  In Progress: {stats['in_progress']}")
        return 0
    
    # Download all
    if args.all:
        print("Starting full backfill for all entities...")
        results = backfiller.backfill_all(args.start_date, args.end_date)
        
        print("\n=== Backfill Results ===")
        for key, result in results.items():
            print(f"\n{key}:")
            print(f"  Total: {result['total']}")
            print(f"  Success: {result['success']}")
            print(f"  Failed: {result['failed']}")
            print(f"  Skipped: {result['skipped']}")
        return 0
    
    # Validate entity and doc-type for specific operations
    if not args.entity:
        parser.error("--entity is required (or use --all)")
    
    # Update mode
    if args.update:
        if args.doc_type:
            # Update specific doc type
            config = BackfillConfig.get_config(args.entity, args.doc_type)
            if not config:
                print(f"Error: Configuration not found for {args.entity}/{args.doc_type}")
                return 1
            
            print(f"Updating {args.entity}/{args.doc_type}...")
            results = backfiller.update(config)
        else:
            # Update all doc types for entity
            configs = BackfillConfig.get_configs_by_entity(args.entity)
            if not configs:
                print(f"Error: No configurations found for {args.entity}")
                return 1
            
            results = {}
            for config in configs:
                print(f"Updating {config.entity_type.value}/{config.doc_type.value}...")
                results[f"{config.entity_type.value}_{config.doc_type.value}"] = backfiller.update(config)
        
        print("\n=== Update Results ===")
        if isinstance(results, dict) and 'total' in results:
            print(f"Total: {results['total']}")
            print(f"Success: {results['success']}")
            print(f"Failed: {results['failed']}")
            print(f"Skipped: {results['skipped']}")
        else:
            for key, result in results.items():
                print(f"\n{key}:")
                print(f"  Total: {result['total']}")
                print(f"  Failed: {result['failed']}")
                print(f"  Skipped: {result['skipped']}")
        return 0
    
    # Regular backfill
    if not args.doc_type:
        parser.error("--doc-type is required for specific entity backfill")
    
    config = BackfillConfig.get_config(args.entity, args.doc_type)
    if not config:
        print(f"Error: Configuration not found for {args.entity}/{args.doc_type}")
        return 1
    
    # Determine date range
    start_date = args.start_date or config.start_date
    end_date = args.end_date or get_current_period(config.frequency)
    
    print(f"Starting backfill for {args.entity}/{args.doc_type}...")
    print(f"Date range: {start_date} to {end_date}")
    
    results = backfiller.backfill(config, start_date, end_date, args.skip_existing)
    
    print("\n=== Backfill Results ===")
    print(f"Total: {results['total']}")
    print(f"Success: {results['success']}")
    print(f"Failed: {results['failed']}")
    print(f"Skipped: {results['skipped']}")
    
    if results['failed'] > 0:
        print("\nFailed downloads:")
        for detail in results['details']:
            if detail['status'] == 'failed':
                print(f"  {detail['period']}: {detail.get('error', 'Unknown error')}")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())