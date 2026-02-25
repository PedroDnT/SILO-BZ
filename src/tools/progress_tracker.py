"""Progress tracking and resume logic for CVM data backfill."""

import json
import sqlite3
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backfill_config import BackfillConfig

class DownloadStatus(Enum):
    """Download status states."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class ProgressTracker:
    """Track download progress and enable resume capability."""
    
    def __init__(self, db_path: Optional[Path] = None):
        """Initialize progress tracker.
        
        Args:
            db_path: Path to SQLite database (default: metadata directory)
        """
        if db_path is None:
            BackfillConfig.METADATA_DIR.mkdir(parents=True, exist_ok=True)
            db_path = BackfillConfig.METADATA_DIR / "progress.db"
        
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database schema."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create downloads table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    period TEXT NOT NULL,
                    status TEXT NOT NULL,
                    file_path TEXT,
                    checksum TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(entity_type, doc_type, period)
                )
            """)
            
            # Create index for faster lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_entity_doc_period 
                ON downloads(entity_type, doc_type, period)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_status 
                ON downloads(status)
            """)
            
            conn.commit()
    
    def mark_in_progress(self, entity_type: str, doc_type: str, period: str):
        """Mark a download as in progress.
        
        Args:
            entity_type: Entity type (e.g., FIDC)
            doc_type: Document type (e.g., INF_MENSAL)
            period: Period identifier (YYYYMM)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO downloads 
                (entity_type, doc_type, period, status, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (entity_type, doc_type, period, DownloadStatus.IN_PROGRESS.value, datetime.now()))
            conn.commit()
    
    def mark_completed(self, entity_type: str, doc_type: str, period: str,
                       file_path: str, checksum: str):
        """Mark a download as completed.
        
        Args:
            entity_type: Entity type
            doc_type: Document type
            period: Period identifier
            file_path: Path to downloaded file
            checksum: File checksum (SHA256)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO downloads 
                (entity_type, doc_type, period, status, file_path, checksum, 
                 error_message, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """, (entity_type, doc_type, period, DownloadStatus.COMPLETED.value,
                  file_path, checksum, datetime.now()))
            conn.commit()
    
    def mark_failed(self, entity_type: str, doc_type: str, period: str,
                    error_message: str):
        """Mark a download as failed.
        
        Args:
            entity_type: Entity type
            doc_type: Document type
            period: Period identifier
            error_message: Error description
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO downloads 
                (entity_type, doc_type, period, status, error_message, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (entity_type, doc_type, period, DownloadStatus.FAILED.value,
                  error_message, datetime.now()))
            conn.commit()
    
    def get_download_status(self, entity_type: str, doc_type: str, 
                           period: str) -> Optional[DownloadStatus]:
        """Get download status for a specific period.
        
        Args:
            entity_type: Entity type
            doc_type: Document type
            period: Period identifier
        
        Returns:
            Download status or None if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status FROM downloads
                WHERE entity_type = ? AND doc_type = ? AND period = ?
            """, (entity_type, doc_type, period))
            
            row = cursor.fetchone()
            if row:
                return DownloadStatus(row[0])
            return None
    
    def get_completed_periods(self, entity_type: str, 
                             doc_type: str) -> List[str]:
        """Get list of completed periods for an entity/doc type.
        
        Args:
            entity_type: Entity type
            doc_type: Document type
        
        Returns:
            List of completed period identifiers
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT period FROM downloads
                WHERE entity_type = ? AND doc_type = ? AND status = ?
                ORDER BY period
            """, (entity_type, doc_type, DownloadStatus.COMPLETED.value))
            
            return [row[0] for row in cursor.fetchall()]
    
    def get_failed_periods(self, entity_type: str, 
                          doc_type: str) -> List[Tuple[str, str]]:
        """Get list of failed periods with error messages.
        
        Args:
            entity_type: Entity type
            doc_type: Document type
        
        Returns:
            List of tuples (period, error_message)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT period, error_message FROM downloads
                WHERE entity_type = ? AND doc_type = ? AND status = ?
                ORDER BY period
            """, (entity_type, doc_type, DownloadStatus.FAILED.value))
            
            return [(row[0], row[1]) for row in cursor.fetchall()]
    
    def get_last_completed_period(self, entity_type: str, 
                                  doc_type: str) -> Optional[str]:
        """Get the most recent completed period.
        
        Args:
            entity_type: Entity type
            doc_type: Document type
        
        Returns:
            Most recent period identifier or None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT period FROM downloads
                WHERE entity_type = ? AND doc_type = ? AND status = ?
                ORDER BY period DESC
                LIMIT 1
            """, (entity_type, doc_type, DownloadStatus.COMPLETED.value))
            
            row = cursor.fetchone()
            return row[0] if row else None
    
    def get_statistics(self, entity_type: str, 
                       doc_type: str) -> Dict[str, int]:
        """Get download statistics for an entity/doc type.
        
        Args:
            entity_type: Entity type
            doc_type: Document type
        
        Returns:
            Dictionary with counts by status
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status, COUNT(*) FROM downloads
                WHERE entity_type = ? AND doc_type = ?
                GROUP BY status
            """, (entity_type, doc_type))
            
            stats = {status.value: 0 for status in DownloadStatus}
            for row in cursor.fetchall():
                stats[row[0]] = row[1]
            
            stats['total'] = sum(stats.values())
            return stats
    
    def get_summary(self) -> Dict[str, Dict[str, int]]:
        """Get overall download summary for all entities.
        
        Returns:
            Nested dictionary with statistics by entity/doc type
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT entity_type, doc_type, status, COUNT(*)
                FROM downloads
                GROUP BY entity_type, doc_type, status
            """)
            
            summary = {}
            for row in cursor.fetchall():
                entity_type, doc_type, status, count = row
                key = f"{entity_type}/{doc_type}"
                
                if key not in summary:
                    summary[key] = {
                        'total': 0,
                        'completed': 0,
                        'failed': 0,
                        'in_progress': 0,
                        'pending': 0
                    }
                
                summary[key]['total'] += count
                if status == DownloadStatus.COMPLETED.value:
                    summary[key]['completed'] = count
                elif status == DownloadStatus.FAILED.value:
                    summary[key]['failed'] = count
                elif status == DownloadStatus.IN_PROGRESS.value:
                    summary[key]['in_progress'] = count
                elif status == DownloadStatus.PENDING.value:
                    summary[key]['pending'] = count
            
            return summary
    
    def reset_in_progress(self):
        """Reset all in-progress downloads to pending.
        
        This is useful for cleaning up after interrupted runs.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE downloads
                SET status = ?, updated_at = ?
                WHERE status = ?
            """, (DownloadStatus.PENDING.value, datetime.now(), 
                  DownloadStatus.IN_PROGRESS.value))
            conn.commit()
    
    def get_file_info(self, entity_type: str, doc_type: str, 
                      period: str) -> Optional[Dict]:
        """Get detailed file information for a specific download.
        
        Args:
            entity_type: Entity type
            doc_type: Document type
            period: Period identifier
        
        Returns:
            Dictionary with file details or None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status, file_path, checksum, error_message, 
                       created_at, updated_at
                FROM downloads
                WHERE entity_type = ? AND doc_type = ? AND period = ?
            """, (entity_type, doc_type, period))
            
            row = cursor.fetchone()
            if row:
                return {
                    'status': row[0],
                    'file_path': row[1],
                    'checksum': row[2],
                    'error_message': row[3],
                    'created_at': row[4],
                    'updated_at': row[5]
                }
            return None
    
    def verify_checksum(self, entity_type: str, doc_type: str, 
                       period: str, file_path: Path) -> bool:
        """Verify file checksum against stored value.
        
        Args:
            entity_type: Entity type
            doc_type: Document type
            period: Period identifier
            file_path: Path to file to verify
        
        Returns:
            True if checksum matches, False otherwise
        """
        import hashlib
        
        # Get stored checksum
        info = self.get_file_info(entity_type, doc_type, period)
        if not info or not info['checksum']:
            return False
        
        stored_checksum = info['checksum']
        
        # Calculate current checksum
        hasher = hashlib.sha256()
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    hasher.update(chunk)
            current_checksum = hasher.hexdigest()
            
            return current_checksum == stored_checksum
        except Exception:
            return False
    
    def export_metadata(self, output_path: Path):
        """Export all metadata to JSON file.
        
        Args:
            output_path: Path to output JSON file
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM downloads ORDER BY entity_type, doc_type, period")
            
            records = [dict(row) for row in cursor.fetchall()]
        
        with open(output_path, 'w') as f:
            json.dump(records, f, indent=2, default=str)
    
    def cleanup_old_failed(self, days: int = 7):
        """Remove failed download records older than specified days.
        
        Args:
            days: Number of days to keep failed records
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM downloads
                WHERE status = ? 
                AND updated_at < datetime('now', '-' || ? || ' days')
            """, (DownloadStatus.FAILED.value, days))
            conn.commit()
            
            deleted_count = cursor.rowcount
            return deleted_count