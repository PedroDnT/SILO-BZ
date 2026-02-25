# Historical Data Backfill Tool

CLI tool for downloading all historical CVM credit market data with resume capability.

## Files

\- \`backfill.py\` \- Main CLI tool  
\- \`backfill\_config.py\` \- Entity configurations  
\- \`progress\_tracker.py\` \- Resume and progress tracking

## Usage

\`\`\`bash

# Download all FIDC monthly data

python backfill.py \--entity FIDC \--doc-type INF\_MENSAL

# Download specific date range

python backfill.py \--entity SECURIT \--doc-type CRA\_MENSAL \--start-date 201901 \--end-date 202412

# Fetch everything

python backfill.py \--all

# Incremental update (only new files)

python backfill.py \--entity FIDC \--update  
\`\`\`

## Supported Entities

| Entity | Document Type | Frequency | Start Date |  
|--------|---------------|-----------|------------|  
| FIDC | INF\_MENSAL | Monthly | 2019-01 |  
| FIP | INF\_QUADRIMESTRAL | Quadrimestral | 2019-01 |  
| FIAGRO | INF\_MENSAL | Monthly | 2021-01 |  
| SECURIT | CRA\_MENSAL | Monthly | 2019-01 |  
| SECURIT | CRI\_MENSAL | Monthly | 2019-01 |  
| SECURIT | LCA\_MENSAL | Monthly | 2019-01 |  
| SECURIT | LCI\_MENSAL | Monthly | 2019-01 |

\---

## backfill.py

\`\`\`python  
\#\!/usr/bin/env python3  
"""Historical Data Backfill CLI Tool for CVM Credit Market Data.

This tool downloads historical CVM data with support for:  
\- Resume capability  
\- Parallel downloads  
\- Progress tracking  
\- Error handling with retries  
\- Incremental updates  
"""

import argparse  
import hashlib  
import logging  
import sys  
import time  
from concurrent.futures import ThreadPoolExecutor, as\_completed  
from datetime import datetime  
from pathlib import Path  
from typing import Dict, List, Optional, Tuple

import requests  
from tqdm import tqdm

from backfill\_config import (  
    BackfillConfig,  
    EntityConfig,  
    EntityType,  
    DocumentType,  
    Frequency,  
    generate\_periods,  
    get\_current\_period,  
)  
from progress\_tracker import ProgressTracker, DownloadStatus

class CVMBackfiller:  
    """Main backfill orchestrator for CVM data."""  
      
    def \_\_init\_\_(self, max\_workers: int \= None, verbose: bool \= False):  
        """Initialize backfiller.  
          
        Args:  
            max\_workers: Maximum number of parallel download workers  
            verbose: Enable verbose logging  
        """  
        self.max\_workers \= max\_workers or BackfillConfig.MAX\_WORKERS  
        self.verbose \= verbose  
        self.progress\_tracker \= ProgressTracker()  
        

# Setup logging

        self.\_setup\_logging()  
        

# Initialize directories

        BackfillConfig.initialize\_directories()  
          
        self.logger.info("CVMBackfiller initialized")  
      
    def \_setup\_logging(self):  
        """Configure logging."""  
        log\_level \= logging.DEBUG if self.verbose else logging.INFO  
        

# Create logger

        self.logger \= logging.getLogger("CVMBackfiller")  
        self.logger.setLevel(log\_level)  
        

# Console handler

        console\_handler \= logging.StreamHandler(sys.stdout)  
        console\_handler.setLevel(log\_level)  
        console\_format \= logging.Formatter(  
            '%(asctime)s \- %(name)s \- %(levelname)s \- %(message)s'  
        )  
        console\_handler.setFormatter(console\_format)  
        self.logger.addHandler(console\_handler)  
        

# File handler

        log\_file \= BackfillConfig.LOG\_DIR / f"backfill\_{datetime.now().strftime('%Y%m%d\_%H%M%S')}.log"  
        file\_handler \= logging.FileHandler(log\_file)  
        file\_handler.setLevel(logging.DEBUG)  
        file\_handler.setFormatter(console\_format)  
        self.logger.addHandler(file\_handler)  
      
    def \_download\_file(self, url: str, file\_path: Path, period: str,   
                       config: EntityConfig) \-\> Tuple\[bool, Optional\[str\], Optional\[str\]\]:  
        """Download a single file with retry logic.  
          
        Args:  
            url: Download URL  
            file\_path: Local file path  
            period: Period identifier  
            config: Entity configuration  
          
        Returns:  
            Tuple of (success, error\_message, checksum)  
        """  
        for attempt in range(BackfillConfig.MAX\_RETRIES):  
            try:  
                self.logger.debug(f"Downloading {url} (attempt {attempt \+ 1}/{BackfillConfig.MAX\_RETRIES})")  
                  
                response \= requests.get(  
                    url,  
                    timeout=BackfillConfig.REQUEST\_TIMEOUT,  
                    stream=True  
                )  
                response.raise\_for\_status()  
                

# Download with progress

                total\_size \= int(response.headers.get('content-length', 0))  
                

# Write file and calculate checksum

                hasher \= hashlib.sha256()  
                with open(file\_path, 'wb') as f:  
                    for chunk in response.iter\_content(chunk\_size=8192):  
                        if chunk:  
                            f.write(chunk)  
                            hasher.update(chunk)  
                  
                checksum \= hasher.hexdigest()  
                  
                self.logger.debug(f"Successfully downloaded {file\_path}")  
                return True, None, checksum  
              
            except requests.exceptions.HTTPError as e:  
                if e.response.status\_code \== 404:

# File doesn't exist on server \- not an error

                    self.logger.debug(f"File not found (404): {url}")  
                    return False, "File not found (404)", None  
                else:  
                    error\_msg \= f"HTTP error {e.response.status\_code}: {str(e)}"  
                    self.logger.warning(f"{error\_msg} \- {url}")  
              
            except requests.exceptions.RequestException as e:  
                error\_msg \= f"Request error: {str(e)}"  
                self.logger.warning(f"{error\_msg} \- {url}")  
              
            except Exception as e:  
                error\_msg \= f"Unexpected error: {str(e)}"  
                self.logger.error(f"{error\_msg} \- {url}", exc\_info=True)  
            

# Retry delay

            if attempt \< BackfillConfig.MAX\_RETRIES \- 1:  
                time.sleep(BackfillConfig.RETRY\_DELAY \* (attempt \+ 1))  
          
        return False, error\_msg, None  
      
    def \_process\_period(self, period: str, config: EntityConfig,   
                        skip\_existing: bool \= True) \-\> Dict:  
        """Process a single period download.  
          
        Args:  
            period: Period identifier (YYYYMM)  
            config: Entity configuration  
            skip\_existing: Skip if already downloaded successfully  
          
        Returns:  
            Download result dictionary  
        """

# Check if already downloaded

        if skip\_existing:  
            status \= self.progress\_tracker.get\_download\_status(  
                config.entity\_type.value,  
                config.doc\_type.value,  
                period  
            )  
            if status \== DownloadStatus.COMPLETED:  
                return {  
                    'period': period,  
                    'status': 'skipped',  
                    'message': 'Already downloaded'  
                }  
        

# Generate URL and file path

        url \= config.get\_url(period)  
        file\_path \= config.get\_file\_path(BackfillConfig.BASE\_DIR, period)  
        

# Mark as in progress

        self.progress\_tracker.mark\_in\_progress(  
            config.entity\_type.value,  
            config.doc\_type.value,  
            period  
        )  
        

# Download file

        success, error\_msg, checksum \= self.\_download\_file(url, file\_path, period, config)  
          
        if success:

# Mark as completed

            self.progress\_tracker.mark\_completed(  
                config.entity\_type.value,  
                config.doc\_type.value,  
                period,  
                str(file\_path),  
                checksum  
            )  
            return {  
                'period': period,  
                'status': 'success',  
                'file\_path': str(file\_path),  
                'checksum': checksum  
            }  
        else:

# Mark as failed

            self.progress\_tracker.mark\_failed(  
                config.entity\_type.value,  
                config.doc\_type.value,  
                period,  
                error\_msg or "Unknown error"  
            )  
            return {  
                'period': period,  
                'status': 'failed',  
                'error': error\_msg  
            }  
      
    def backfill(self, config: EntityConfig, start\_date: str, end\_date: str,  
                 skip\_existing: bool \= True) \-\> Dict:  
        """Backfill data for a specific configuration.  
          
        Args:  
            config: Entity configuration  
            start\_date: Start date in YYYYMM format  
            end\_date: End date in YYYYMM format  
            skip\_existing: Skip already downloaded files  
          
        Returns:  
            Summary dictionary with results  
        """  
        self.logger.info(  
            f"Starting backfill for {config.entity\_type.value}/{config.doc\_type.value} "  
            f"from {start\_date} to {end\_date}"  
        )  
        

# Generate periods

        periods \= generate\_periods(start\_date, end\_date, config.frequency)  
        self.logger.info(f"Generated {len(periods)} periods to process")  
        

# Track results

        results \= {  
            'total': len(periods),  
            'success': 0,  
            'failed': 0,  
            'skipped': 0,  
            'details': \[\]  
        }  
        

# Process downloads in parallel

        with ThreadPoolExecutor(max\_workers=self.max\_workers) as executor:

# Submit all tasks

            future\_to\_period \= {  
                executor.submit(self.\_process\_period, period, config, skip\_existing): period  
                for period in periods  
            }  
            

# Process completed tasks with progress bar

            with tqdm(total=len(periods), desc=f"{config.entity\_type.value}/{config.doc\_type.value}") as pbar:  
                for future in as\_completed(future\_to\_period):  
                    period \= future\_to\_period\[future\]  
                    try:  
                        result \= future.result()  
                        results\['details'\].append(result)  
                          
                        if result\['status'\] \== 'success':  
                            results\['success'\] \+= 1  
                        elif result\['status'\] \== 'failed':  
                            results\['failed'\] \+= 1  
                        elif result\['status'\] \== 'skipped':  
                            results\['skipped'\] \+= 1  
                          
                        pbar.update(1)  
                      
                    except Exception as e:  
                        self.logger.error(f"Error processing period {period}: {str(e)}", exc\_info=True)  
                        results\['failed'\] \+= 1  
                        results\['details'\].append({  
                            'period': period,  
                            'status': 'failed',  
                            'error': str(e)  
                        })  
                        pbar.update(1)  
          
        self.logger.info(  
            f"Backfill completed: {results\['success'\]} success, "  
            f"{results\['failed'\]} failed, {results\['skipped'\]} skipped"  
        )  
          
        return results  
      
    def backfill\_all(self, start\_date: Optional\[str\] \= None,   
                     end\_date: Optional\[str\] \= None) \-\> Dict:  
        """Backfill all configured entities.  
          
        Args:  
            start\_date: Override start date (YYYYMM)  
            end\_date: Override end date (YYYYMM)  
          
        Returns:  
            Combined summary dictionary  
        """  
        all\_results \= {}  
          
        for key, config in BackfillConfig.ENTITY\_CONFIGS.items():

# Use config start date if not overridden

            effective\_start \= start\_date or config.start\_date  
            effective\_end \= end\_date or get\_current\_period(config.frequency)  
              
            results \= self.backfill(config, effective\_start, effective\_end)  
            all\_results\[key\] \= results  
          
        return all\_results  
      
    def update(self, config: EntityConfig) \-\> Dict:  
        """Incremental update \- fetch only new data since last download.  
          
        Args:  
            config: Entity configuration  
          
        Returns:  
            Summary dictionary with results  
        """

# Get last downloaded period

        last\_period \= self.progress\_tracker.get\_last\_completed\_period(  
            config.entity\_type.value,  
            config.doc\_type.value  
        )  
          
        if last\_period:

# Start from next period after last downloaded

            year \= int(last\_period\[:4\])  
            month \= int(last\_period\[4:6\])  
              
            if config.frequency \== Frequency.MONTHLY:  
                month \+= 1  
                if month \> 12:  
                    month \= 1  
                    year \+= 1  
            elif config.frequency \== Frequency.QUADRIMESTRAL:  
                if month \== 1:  
                    month \= 5  
                elif month \== 5:  
                    month \= 9  
                else:  
                    month \= 1  
                    year \+= 1  
              
            start\_date \= f"{year}{month:02d}"  
        else:

# No previous downloads, use config start date

            start\_date \= config.start\_date  
          
        end\_date \= get\_current\_period(config.frequency)  
          
        self.logger.info(f"Incremental update from {start\_date} to {end\_date}")  
          
        return self.backfill(config, start\_date, end\_date, skip\_existing=True)  
      
    def get\_summary(self) \-\> Dict:  
        """Get overall download summary.  
          
        Returns:  
            Summary statistics  
        """  
        return self.progress\_tracker.get\_summary()

def main():  
    """Main CLI entry point."""  
    parser \= argparse.ArgumentParser(  
        description="Historical Data Backfill Tool for CVM Credit Market Data",  
        formatter\_class=argparse.RawDescriptionHelpFormatter,  
        epilog="""  
Examples:

# Download all FIDC monthly reports from 2019 to 2024

  python backfill.py \--entity FIDC \--doc-type INF\_MENSAL \--start-date 201901 \--end-date 202412


# Download everything

  python backfill.py \--all


# Incremental update for SECURIT

  python backfill.py \--entity SECURIT \--update


# Update specific document type

  python backfill.py \--entity SECURIT \--doc-type CRA\_MENSAL \--update


# Get download summary

  python backfill.py \--summary  
        """  
    )  
    

# Entity and document type selection

    parser.add\_argument(  
        '--entity',  
        type=str,  
        choices=\[e.value for e in EntityType\],  
        help='Entity type to download'  
    )  
    parser.add\_argument(  
        '--doc-type',  
        type=str,  
        choices=\[d.value for d in DocumentType\],  
        help='Document type to download'  
    )  
    

# Date range

    parser.add\_argument(  
        '--start-date',  
        type=str,  
        help='Start date in YYYYMM format (e.g., 201901)'  
    )  
    parser.add\_argument(  
        '--end-date',  
        type=str,  
        help='End date in YYYYMM format (e.g., 202412)'  
    )  
    

# Operations

    parser.add\_argument(  
        '--all',  
        action='store\_true',  
        help='Download all configured entities'  
    )  
    parser.add\_argument(  
        '--update',  
        action='store\_true',  
        help='Incremental update (fetch only new data)'  
    )  
    parser.add\_argument(  
        '--summary',  
        action='store\_true',  
        help='Show download summary and exit'  
    )  
    

# Configuration

    parser.add\_argument(  
        '--workers',  
        type=int,  
        default=BackfillConfig.MAX\_WORKERS,  
        help=f'Number of parallel workers (default: {BackfillConfig.MAX\_WORKERS})'  
    )  
    parser.add\_argument(  
        '--skip-existing',  
        action='store\_true',  
        default=True,  
        help='Skip already downloaded files (default: True)'  
    )  
    parser.add\_argument(  
        '--verbose',  
        action='store\_true',  
        help='Enable verbose logging'  
    )  
      
    args \= parser.parse\_args()  
    

# Create backfiller

    backfiller \= CVMBackfiller(max\_workers=args.workers, verbose=args.verbose)  
    

# Show summary

    if args.summary:  
        summary \= backfiller.get\_summary()  
        print("\\n=== Download Summary \===")  
        for entity, stats in summary.items():  
            print(f"\\n{entity}:")  
            print(f"  Total: {stats\['total'\]}")  
            print(f"  Completed: {stats\['completed'\]}")  
            print(f"  Failed: {stats\['failed'\]}")  
            print(f"  In Progress: {stats\['in\_progress'\]}")  
        return 0  
    

# Download all

    if args.all:  
        print("Starting full backfill for all entities...")  
        results \= backfiller.backfill\_all(args.start\_date, args.end\_date)  
          
        print("\\n=== Backfill Results \===")  
        for key, result in results.items():  
            print(f"\\n{key}:")  
            print(f"  Total: {result\['total'\]}")  
            print(f"  Success: {result\['success'\]}")  
            print(f"  Failed: {result\['failed'\]}")  
            print(f"  Skipped: {result\['skipped'\]}")  
        return 0  
    

# Validate entity and doc-type for specific operations

    if not args.entity:  
        parser.error("--entity is required (or use \--all)")  
    

# Update mode

    if args.update:  
        if args.doc\_type:

# Update specific doc type

            config \= BackfillConfig.get\_config(args.entity, args.doc\_type)  
            if not config:  
                print(f"Error: Configuration not found for {args.entity}/{args.doc\_type}")  
                return 1  
              
            print(f"Updating {args.entity}/{args.doc\_type}...")  
            results \= backfiller.update(config)  
        else:

# Update all doc types for entity

            configs \= BackfillConfig.get\_configs\_by\_entity(args.entity)  
            if not configs:  
                print(f"Error: No configurations found for {args.entity}")  
                return 1  
              
            results \= {}  
            for config in configs:  
                print(f"Updating {config.entity\_type.value}/{config.doc\_type.value}...")  
                results\[f"{config.entity\_type.value}\_{config.doc\_type.value}"\] \= backfiller.update(config)  
          
        print("\\n=== Update Results \===")  
        if isinstance(results, dict) and 'total' in results:  
            print(f"Total: {results\['total'\]}")  
            print(f"Success: {results\['success'\]}")  
            print(f"Failed: {results\['failed'\]}")  
            print(f"Skipped: {results\['skipped'\]}")  
        else:  
            for key, result in results.items():  
                print(f"\\n{key}:")  
                print(f"  Total: {result\['total'\]}")  
                print(f"  Success: {result\['success'\]}")  
                print(f"  Failed: {result\['failed'\]}")  
                print(f"  Skipped: {result\['skipped'\]}")  
        return 0  
    

# Regular backfill

    if not args.doc\_type:  
        parser.error("--doc-type is required for specific entity backfill")  
      
    config \= BackfillConfig.get\_config(args.entity, args.doc\_type)  
    if not config:  
        print(f"Error: Configuration not found for {args.entity}/{args.doc\_type}")  
        return 1  
    

# Determine date range

    start\_date \= args.start\_date or config.start\_date  
    end\_date \= args.end\_date or get\_current\_period(config.frequency)  
      
    print(f"Starting backfill for {args.entity}/{args.doc\_type}...")  
    print(f"Date range: {start\_date} to {end\_date}")  
      
    results \= backfiller.backfill(config, start\_date, end\_date, args.skip\_existing)  
      
    print("\\n=== Backfill Results \===")  
    print(f"Total: {results\['total'\]}")  
    print(f"Success: {results\['success'\]}")  
    print(f"Failed: {results\['failed'\]}")  
    print(f"Skipped: {results\['skipped'\]}")  
      
    if results\['failed'\] \> 0:  
        print("\\nFailed downloads:")  
        for detail in results\['details'\]:  
            if detail\['status'\] \== 'failed':  
                print(f"  {detail\['period'\]}: {detail.get('error', 'Unknown error')}")  
      
    return 0

if \_\_name\_\_ \== '\_\_main\_\_':  
    sys.exit(main())

\`\`\`

\---

## backfill\_config.py

\`\`\`python  
"""Configuration for CVM credit market data backfill operations."""

from dataclasses import dataclass  
from datetime import datetime  
from enum import Enum  
from pathlib import Path  
from typing import Dict, List, Optional

class EntityType(Enum):  
    """Supported CVM entity types."""  
    FIDC \= "FIDC"  
    FIP \= "FIP"  
    FIAGRO \= "FIAGRO"  
    SECURIT \= "SECURIT"

class DocumentType(Enum):  
    """Supported document types."""  
    INF\_MENSAL \= "INF\_MENSAL"  
    INF\_QUADRIMESTRAL \= "INF\_QUADRIMESTRAL"  
    CRA\_MENSAL \= "CRA\_MENSAL"  
    CRI\_MENSAL \= "CRI\_MENSAL"  
    LCA\_MENSAL \= "LCA\_MENSAL"  
    LCI\_MENSAL \= "LCI\_MENSAL"

class Frequency(Enum):  
    """Data frequency types."""  
    MONTHLY \= "monthly"  
    QUADRIMESTRAL \= "quadrimestral"

@dataclass  
class EntityConfig:  
    """Configuration for a specific entity and document type."""  
    entity\_type: EntityType  
    doc\_type: DocumentType  
    frequency: Frequency  
    start\_date: str  \# YYYYMM format  
    base\_url\_template: str  
    file\_extension: str \= "csv"  
      
    def get\_url(self, period: str) \-\> str:  
        """Generate download URL for a specific period."""  
        return self.base\_url\_template.format(  
            entity=self.entity\_type.value,  
            doc\_type=self.doc\_type.value,  
            period=period  
        )  
      
    def get\_file\_path(self, base\_dir: Path, period: str) \-\> Path:  
        """Generate local file path for a specific period."""  
        entity\_dir \= base\_dir / self.entity\_type.value / self.doc\_type.value  
        entity\_dir.mkdir(parents=True, exist\_ok=True)  
        return entity\_dir / f"{period}.{self.file\_extension}"

class BackfillConfig:  
    """Main configuration for backfill operations."""  
    

# Base configuration

    BASE\_DIR \= Path("data/cvm\_backfill")  
    METADATA\_DIR \= BASE\_DIR / ".metadata"  
    LOG\_DIR \= BASE\_DIR / ".logs"  
    

# Download configuration

    MAX\_WORKERS \= 5  
    REQUEST\_TIMEOUT \= 60  \# seconds  
    MAX\_RETRIES \= 3  
    RETRY\_DELAY \= 2  \# seconds  
    

# CVM data URLs (adjust these to actual CVM endpoints)

    CVM\_BASE\_URL \= "https://dados.cvm.gov.br/dados"  
    

# Entity configurations

    ENTITY\_CONFIGS: Dict\[str, EntityConfig\] \= {

# FIDC \- Monthly reports since 2019

        "FIDC\_INF\_MENSAL": EntityConfig(  
            entity\_type=EntityType.FIDC,  
            doc\_type=DocumentType.INF\_MENSAL,  
            frequency=Frequency.MONTHLY,  
            start\_date="201901",  
            base\_url\_template=f"{CVM\_BASE\_URL}/FIDC/DOC/INF\_MENSAL/DADOS/inf\_mensal\_fidc\_{{period}}.csv"  
        ),  
        

# FIP \- Quadrimestral reports since 2019

        "FIP\_INF\_QUADRIMESTRAL": EntityConfig(  
            entity\_type=EntityType.FIP,  
            doc\_type=DocumentType.INF\_QUADRIMESTRAL,  
            frequency=Frequency.QUADRIMESTRAL,  
            start\_date="201901",  
            base\_url\_template=f"{CVM\_BASE\_URL}/FIP/DOC/INF\_QUADRIMESTRAL/DADOS/inf\_quadrimestral\_fip\_{{period}}.csv"  
        ),  
        

# FIAGRO \- Monthly reports since 2021

        "FIAGRO\_INF\_MENSAL": EntityConfig(  
            entity\_type=EntityType.FIAGRO,  
            doc\_type=DocumentType.INF\_MENSAL,  
            frequency=Frequency.MONTHLY,  
            start\_date="202101",  
            base\_url\_template=f"{CVM\_BASE\_URL}/FIAGRO/DOC/INF\_MENSAL/DADOS/inf\_mensal\_fiagro\_{{period}}.csv"  
        ),  
        

# SECURIT \- CRA Monthly since 2019

        "SECURIT\_CRA\_MENSAL": EntityConfig(  
            entity\_type=EntityType.SECURIT,  
            doc\_type=DocumentType.CRA\_MENSAL,  
            frequency=Frequency.MONTHLY,  
            start\_date="201901",  
            base\_url\_template=f"{CVM\_BASE\_URL}/SECURIT/DOC/CRA\_MENSAL/DADOS/cra\_mensal\_{{period}}.csv"  
        ),  
        

# SECURIT \- CRI Monthly since 2019

        "SECURIT\_CRI\_MENSAL": EntityConfig(  
            entity\_type=EntityType.SECURIT,  
            doc\_type=DocumentType.CRI\_MENSAL,  
            frequency=Frequency.MONTHLY,  
            start\_date="201901",  
            base\_url\_template=f"{CVM\_BASE\_URL}/SECURIT/DOC/CRI\_MENSAL/DADOS/cri\_mensal\_{{period}}.csv"  
        ),  
        

# SECURIT \- LCA Monthly since 2019

        "SECURIT\_LCA\_MENSAL": EntityConfig(  
            entity\_type=EntityType.SECURIT,  
            doc\_type=DocumentType.LCA\_MENSAL,  
            frequency=Frequency.MONTHLY,  
            start\_date="201901",  
            base\_url\_template=f"{CVM\_BASE\_URL}/SECURIT/DOC/LCA\_MENSAL/DADOS/lca\_mensal\_{{period}}.csv"  
        ),  
        

# SECURIT \- LCI Monthly since 2019

        "SECURIT\_LCI\_MENSAL": EntityConfig(  
            entity\_type=EntityType.SECURIT,  
            doc\_type=DocumentType.LCI\_MENSAL,  
            frequency=Frequency.MONTHLY,  
            start\_date="201901",  
            base\_url\_template=f"{CVM\_BASE\_URL}/SECURIT/DOC/LCI\_MENSAL/DADOS/lci\_mensal\_{{period}}.csv"  
        ),  
    }  
      
    @classmethod  
    def get\_config(cls, entity: str, doc\_type: str) \-\> Optional\[EntityConfig\]:  
        """Get configuration for specific entity and document type."""  
        key \= f"{entity}\_{doc\_type}"  
        return cls.ENTITY\_CONFIGS.get(key)  
      
    @classmethod  
    def get\_all\_configs(cls) \-\> List\[EntityConfig\]:  
        """Get all entity configurations."""  
        return list(cls.ENTITY\_CONFIGS.values())  
      
    @classmethod  
    def get\_configs\_by\_entity(cls, entity: str) \-\> List\[EntityConfig\]:  
        """Get all configurations for a specific entity."""  
        return \[  
            config for config in cls.ENTITY\_CONFIGS.values()  
            if config.entity\_type.value \== entity  
        \]  
      
    @classmethod  
    def initialize\_directories(cls):  
        """Create necessary directories."""  
        cls.BASE\_DIR.mkdir(parents=True, exist\_ok=True)  
        cls.METADATA\_DIR.mkdir(parents=True, exist\_ok=True)  
        cls.LOG\_DIR.mkdir(parents=True, exist\_ok=True)  
        

# Create entity directories

        for config in cls.ENTITY\_CONFIGS.values():  
            entity\_dir \= cls.BASE\_DIR / config.entity\_type.value / config.doc\_type.value  
            entity\_dir.mkdir(parents=True, exist\_ok=True)

def generate\_periods(start\_date: str, end\_date: str, frequency: Frequency) \-\> List\[str\]:  
    """Generate list of periods between start and end dates.  
      
    Args:  
        start\_date: Start date in YYYYMM format  
        end\_date: End date in YYYYMM format  
        frequency: Data frequency (monthly or quadrimestral)  
      
    Returns:  
        List of period strings in YYYYMM format  
    """  
    start\_year \= int(start\_date\[:4\])  
    start\_month \= int(start\_date\[4:6\])  
    end\_year \= int(end\_date\[:4\])  
    end\_month \= int(end\_date\[4:6\])  
      
    periods \= \[\]  
      
    if frequency \== Frequency.MONTHLY:

# Generate all months

        year, month \= start\_year, start\_month  
        while year \< end\_year or (year \== end\_year and month \<= end\_month):  
            periods.append(f"{year}{month:02d}")  
            month \+= 1  
            if month \> 12:  
                month \= 1  
                year \+= 1  
      
    elif frequency \== Frequency.QUADRIMESTRAL:

# Generate quadrimestral periods (every 4 months: 01, 05, 09\)

        year \= start\_year  
        months \= \[1, 5, 9\]  
          
        while year \<= end\_year:  
            for month in months:  
                if (year \> end\_year or   
                    (year \== end\_year and month \> end\_month)):  
                    break  
                if (year \> start\_year or   
                    (year \== start\_year and month \>= start\_month)):  
                    periods.append(f"{year}{month:02d}")  
            year \+= 1  
      
    return periods

def get\_current\_period(frequency: Frequency) \-\> str:  
    """Get current period based on frequency.  
      
    Returns:  
        Current period in YYYYMM format  
    """  
    now \= datetime.now()  
    year \= now.year  
    month \= now.month  
      
    if frequency \== Frequency.QUADRIMESTRAL:

# Find the most recent quadrimestral period

        if month \>= 9:  
            month \= 9  
        elif month \>= 5:  
            month \= 5  
        else:  
            month \= 1  
      
    return f"{year}{month:02d}"

\`\`\`

\---

## progress\_tracker.py

\`\`\`python  
"""Progress tracking and resume logic for CVM data backfill."""

import json  
import sqlite3  
from datetime import datetime  
from enum import Enum  
from pathlib import Path  
from typing import Dict, List, Optional, Tuple

from backfill\_config import BackfillConfig

class DownloadStatus(Enum):  
    """Download status states."""  
    PENDING \= "pending"  
    IN\_PROGRESS \= "in\_progress"  
    COMPLETED \= "completed"  
    FAILED \= "failed"

class ProgressTracker:  
    """Track download progress and enable resume capability."""  
      
    def \_\_init\_\_(self, db\_path: Optional\[Path\] \= None):  
        """Initialize progress tracker.  
          
        Args:  
            db\_path: Path to SQLite database (default: metadata directory)  
        """  
        if db\_path is None:  
            BackfillConfig.METADATA\_DIR.mkdir(parents=True, exist\_ok=True)  
            db\_path \= BackfillConfig.METADATA\_DIR / "progress.db"  
          
        self.db\_path \= db\_path  
        self.\_init\_database()  
      
    def \_init\_database(self):  
        """Initialize SQLite database schema."""  
        with sqlite3.connect(self.db\_path) as conn:  
            cursor \= conn.cursor()  
            

# Create downloads table

            cursor.execute("""  
                CREATE TABLE IF NOT EXISTS downloads (  
                    id INTEGER PRIMARY KEY AUTOINCREMENT,  
                    entity\_type TEXT NOT NULL,  
                    doc\_type TEXT NOT NULL,  
                    period TEXT NOT NULL,  
                    status TEXT NOT NULL,  
                    file\_path TEXT,  
                    checksum TEXT,  
                    error\_message TEXT,  
                    created\_at TIMESTAMP DEFAULT CURRENT\_TIMESTAMP,  
                    updated\_at TIMESTAMP DEFAULT CURRENT\_TIMESTAMP,  
                    UNIQUE(entity\_type, doc\_type, period)  
                )  
            """)  
            

# Create index for faster lookups

            cursor.execute("""  
                CREATE INDEX IF NOT EXISTS idx\_entity\_doc\_period   
                ON downloads(entity\_type, doc\_type, period)  
            """)  
              
            cursor.execute("""  
                CREATE INDEX IF NOT EXISTS idx\_status   
                ON downloads(status)  
            """)  
              
            conn.commit()  
      
    def mark\_in\_progress(self, entity\_type: str, doc\_type: str, period: str):  
        """Mark a download as in progress.  
          
        Args:  
            entity\_type: Entity type (e.g., FIDC)  
            doc\_type: Document type (e.g., INF\_MENSAL)  
            period: Period identifier (YYYYMM)  
        """  
        with sqlite3.connect(self.db\_path) as conn:  
            cursor \= conn.cursor()  
            cursor.execute("""  
                INSERT OR REPLACE INTO downloads   
                (entity\_type, doc\_type, period, status, updated\_at)  
                VALUES (?, ?, ?, ?, ?)  
            """, (entity\_type, doc\_type, period, DownloadStatus.IN\_PROGRESS.value, datetime.now()))  
            conn.commit()  
      
    def mark\_completed(self, entity\_type: str, doc\_type: str, period: str,  
                       file\_path: str, checksum: str):  
        """Mark a download as completed.  
          
        Args:  
            entity\_type: Entity type  
            doc\_type: Document type  
            period: Period identifier  
            file\_path: Path to downloaded file  
            checksum: File checksum (SHA256)  
        """  
        with sqlite3.connect(self.db\_path) as conn:  
            cursor \= conn.cursor()  
            cursor.execute("""  
                INSERT OR REPLACE INTO downloads   
                (entity\_type, doc\_type, period, status, file\_path, checksum,   
                 error\_message, updated\_at)  
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?)  
            """, (entity\_type, doc\_type, period, DownloadStatus.COMPLETED.value,  
                  file\_path, checksum, datetime.now()))  
            conn.commit()  
      
    def mark\_failed(self, entity\_type: str, doc\_type: str, period: str,  
                    error\_message: str):  
        """Mark a download as failed.  
          
        Args:  
            entity\_type: Entity type  
            doc\_type: Document type  
            period: Period identifier  
            error\_message: Error description  
        """  
        with sqlite3.connect(self.db\_path) as conn:  
            cursor \= conn.cursor()  
            cursor.execute("""  
                INSERT OR REPLACE INTO downloads   
                (entity\_type, doc\_type, period, status, error\_message, updated\_at)  
                VALUES (?, ?, ?, ?, ?, ?)  
            """, (entity\_type, doc\_type, period, DownloadStatus.FAILED.value,  
                  error\_message, datetime.now()))  
            conn.commit()  
      
    def get\_download\_status(self, entity\_type: str, doc\_type: str,   
                           period: str) \-\> Optional\[DownloadStatus\]:  
        """Get download status for a specific period.  
          
        Args:  
            entity\_type: Entity type  
            doc\_type: Document type  
            period: Period identifier  
          
        Returns:  
            Download status or None if not found  
        """  
        with sqlite3.connect(self.db\_path) as conn:  
            cursor \= conn.cursor()  
            cursor.execute("""  
                SELECT status FROM downloads  
                WHERE entity\_type \= ? AND doc\_type \= ? AND period \= ?  
            """, (entity\_type, doc\_type, period))  
              
            row \= cursor.fetchone()  
            if row:  
                return DownloadStatus(row\[0\])  
            return None  
      
    def get\_completed\_periods(self, entity\_type: str,   
                             doc\_type: str) \-\> List\[str\]:  
        """Get list of completed periods for an entity/doc type.  
          
        Args:  
            entity\_type: Entity type  
            doc\_type: Document type  
          
        Returns:  
            List of completed period identifiers  
        """  
        with sqlite3.connect(self.db\_path) as conn:  
            cursor \= conn.cursor()  
            cursor.execute("""  
                SELECT period FROM downloads  
                WHERE entity\_type \= ? AND doc\_type \= ? AND status \= ?  
                ORDER BY period  
            """, (entity\_type, doc\_type, DownloadStatus.COMPLETED.value))  
              
            return \[row\[0\] for row in cursor.fetchall()\]  
      
    def get\_failed\_periods(self, entity\_type: str,   
                          doc\_type: str) \-\> List\[Tuple\[str, str\]\]:  
        """Get list of failed periods with error messages.  
          
        Args:  
            entity\_type: Entity type  
            doc\_type: Document type  
          
        Returns:  
            List of tuples (period, error\_message)  
        """  
        with sqlite3.connect(self.db\_path) as conn:  
            cursor \= conn.cursor()  
            cursor.execute("""  
                SELECT period, error\_message FROM downloads  
                WHERE entity\_type \= ? AND doc\_type \= ? AND status \= ?  
                ORDER BY period  
            """, (entity\_type, doc\_type, DownloadStatus.FAILED.value))  
              
            return \[(row\[0\], row\[1\]) for row in cursor.fetchall()\]  
      
    def get\_last\_completed\_period(self, entity\_type: str,   
                                  doc\_type: str) \-\> Optional\[str\]:  
        """Get the most recent completed period.  
          
        Args:  
            entity\_type: Entity type  
            doc\_type: Document type  
          
        Returns:  
            Most recent period identifier or None  
        """  
        with sqlite3.connect(self.db\_path) as conn:  
            cursor \= conn.cursor()  
            cursor.execute("""  
                SELECT period FROM downloads  
                WHERE entity\_type \= ? AND doc\_type \= ? AND status \= ?  
                ORDER BY period DESC  
                LIMIT 1  
            """, (entity\_type, doc\_type, DownloadStatus.COMPLETED.value))  
              
            row \= cursor.fetchone()  
            return row\[0\] if row else None  
      
    def get\_statistics(self, entity\_type: str,   
                       doc\_type: str) \-\> Dict\[str, int\]:  
        """Get download statistics for an entity/doc type.  
          
        Args:  
            entity\_type: Entity type  
            doc\_type: Document type  
          
        Returns:  
            Dictionary with counts by status  
        """  
        with sqlite3.connect(self.db\_path) as conn:  
            cursor \= conn.cursor()  
            cursor.execute("""  
                SELECT status, COUNT(\*) FROM downloads  
                WHERE entity\_type \= ? AND doc\_type \= ?  
                GROUP BY status  
            """, (entity\_type, doc\_type))  
              
            stats \= {status.value: 0 for status in DownloadStatus}  
            for row in cursor.fetchall():  
                stats\[row\[0\]\] \= row\[1\]  
              
            stats\['total'\] \= sum(stats.values())  
            return stats  
      
    def get\_summary(self) \-\> Dict\[str, Dict\[str, int\]\]:  
        """Get overall download summary for all entities.  
          
        Returns:  
            Nested dictionary with statistics by entity/doc type  
        """  
        with sqlite3.connect(self.db\_path) as conn:  
            cursor \= conn.cursor()  
            cursor.execute("""  
                SELECT entity\_type, doc\_type, status, COUNT(\*)  
                FROM downloads  
                GROUP BY entity\_type, doc\_type, status  
            """)  
              
            summary \= {}  
            for row in cursor.fetchall():  
                entity\_type, doc\_type, status, count \= row  
                key \= f"{entity\_type}/{doc\_type}"  
                  
                if key not in summary:  
                    summary\[key\] \= {  
                        'total': 0,  
                        'completed': 0,  
                        'failed': 0,  
                        'in\_progress': 0,  
                        'pending': 0  
                    }  
                  
                summary\[key\]\['total'\] \+= count  
                if status \== DownloadStatus.COMPLETED.value:  
                    summary\[key\]\['completed'\] \= count  
                elif status \== DownloadStatus.FAILED.value:  
                    summary\[key\]\['failed'\] \= count  
                elif status \== DownloadStatus.IN\_PROGRESS.value:  
                    summary\[key\]\['in\_progress'\] \= count  
                elif status \== DownloadStatus.PENDING.value:  
                    summary\[key\]\['pending'\] \= count  
              
            return summary  
      
    def reset\_in\_progress(self):  
        """Reset all in-progress downloads to pending.  
          
        This is useful for cleaning up after interrupted runs.  
        """  
        with sqlite3.connect(self.db\_path) as conn:  
            cursor \= conn.cursor()  
            cursor.execute("""  
                UPDATE downloads  
                SET status \= ?, updated\_at \= ?  
                WHERE status \= ?  
            """, (DownloadStatus.PENDING.value, datetime.now(),   
                  DownloadStatus.IN\_PROGRESS.value))  
            conn.commit()  
      
    def get\_file\_info(self, entity\_type: str, doc\_type: str,   
                      period: str) \-\> Optional\[Dict\]:  
        """Get detailed file information for a specific download.  
          
        Args:  
            entity\_type: Entity type  
            doc\_type: Document type  
            period: Period identifier  
          
        Returns:  
            Dictionary with file details or None  
        """  
        with sqlite3.connect(self.db\_path) as conn:  
            cursor \= conn.cursor()  
            cursor.execute("""  
                SELECT status, file\_path, checksum, error\_message,   
                       created\_at, updated\_at  
                FROM downloads  
                WHERE entity\_type \= ? AND doc\_type \= ? AND period \= ?  
            """, (entity\_type, doc\_type, period))  
              
            row \= cursor.fetchone()  
            if row:  
                return {  
                    'status': row\[0\],  
                    'file\_path': row\[1\],  
                    'checksum': row\[2\],  
                    'error\_message': row\[3\],  
                    'created\_at': row\[4\],  
                    'updated\_at': row\[5\]  
                }  
            return None  
      
    def verify\_checksum(self, entity\_type: str, doc\_type: str,   
                       period: str, file\_path: Path) \-\> bool:  
        """Verify file checksum against stored value.  
          
        Args:  
            entity\_type: Entity type  
            doc\_type: Document type  
            period: Period identifier  
            file\_path: Path to file to verify  
          
        Returns:  
            True if checksum matches, False otherwise  
        """  
        import hashlib  
        

# Get stored checksum

        info \= self.get\_file\_info(entity\_type, doc\_type, period)  
        if not info or not info\['checksum'\]:  
            return False  
          
        stored\_checksum \= info\['checksum'\]  
        

# Calculate current checksum

        hasher \= hashlib.sha256()  
        try:  
            with open(file\_path, 'rb') as f:  
                for chunk in iter(lambda: f.read(8192), b''):  
                    hasher.update(chunk)  
            current\_checksum \= hasher.hexdigest()  
              
            return current\_checksum \== stored\_checksum  
        except Exception:  
            return False  
      
    def export\_metadata(self, output\_path: Path):  
        """Export all metadata to JSON file.  
          
        Args:  
            output\_path: Path to output JSON file  
        """  
        with sqlite3.connect(self.db\_path) as conn:  
            conn.row\_factory \= sqlite3.Row  
            cursor \= conn.cursor()  
            cursor.execute("SELECT \* FROM downloads ORDER BY entity\_type, doc\_type, period")  
              
            records \= \[dict(row) for row in cursor.fetchall()\]  
          
        with open(output\_path, 'w') as f:  
            json.dump(records, f, indent=2, default=str)  
      
    def cleanup\_old\_failed(self, days: int \= 7):  
        """Remove failed download records older than specified days.  
          
        Args:  
            days: Number of days to keep failed records  
        """  
        with sqlite3.connect(self.db\_path) as conn:  
            cursor \= conn.cursor()  
            cursor.execute("""  
                DELETE FROM downloads  
                WHERE status \= ?   
                AND updated\_at \< datetime('now', '-' || ? || ' days')  
            """, (DownloadStatus.FAILED.value, days))  
            conn.commit()  
              
            deleted\_count \= cursor.rowcount  
            return deleted\_count

\`\`\`

\---

\*Generated: February 2026\*  
