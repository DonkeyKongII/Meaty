//! Persistence for structured action items extracted from completed summaries.
use sqlx::SqlitePool;

pub struct ActionItemsRepository;

impl ActionItemsRepository {
    /// Replace a meeting's action items with the given (text, completed) rows.
    ///
    /// Called when a summary completes: the freshly parsed rows are the single
    /// source of truth, so old rows for the meeting are deleted first.
    pub async fn replace_for_meeting(
        pool: &SqlitePool,
        meeting_id: &str,
        items: &[(String, bool)],
    ) -> Result<(), sqlx::Error> {
        let mut tx = pool.begin().await?;
        sqlx::query("DELETE FROM action_items WHERE meeting_id = ?")
            .bind(meeting_id)
            .execute(&mut *tx)
            .await?;
        for (text, completed) in items {
            sqlx::query(
                "INSERT INTO action_items (id, meeting_id, text, completed, created_at) VALUES (?, ?, ?, ?, ?)",
            )
            .bind(uuid::Uuid::new_v4().to_string())
            .bind(meeting_id)
            .bind(text)
            .bind(completed)
            .bind(chrono::Utc::now().to_rfc3339())
            .execute(&mut *tx)
            .await?;
        }
        tx.commit().await
    }
}
