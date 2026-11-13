use api_rs::migration::{Migrator, MigratorTrait};
use sea_orm::{
    ConnectionTrait, Database, DatabaseTransaction, DbBackend, DbErr, FromQueryResult, RuntimeErr,
    Statement, TransactionTrait,
};

#[derive(Debug, PartialEq, Eq, FromQueryResult)]
struct MigratedUser {
    id: String,
    email: String,
    uid: i64,
    username: Option<String>,
    nickname: Option<String>,
    locale: String,
}

async fn users(db: &DatabaseTransaction) -> Vec<MigratedUser> {
    MigratedUser::find_by_statement(Statement::from_string(
        DbBackend::Postgres,
        r#"SELECT id::text, email, uid, username, nickname, locale
           FROM public."user" ORDER BY email"#,
    ))
    .all(db)
    .await
    .unwrap()
}

async fn assert_rejected(db: &DatabaseTransaction, sql: &str, expected_code: &str) {
    // A failed statement must not abort the outer test transaction.
    let savepoint = db.begin().await.unwrap();
    let error = savepoint.execute_unprepared(sql).await.unwrap_err();
    match error {
        DbErr::Exec(RuntimeErr::SqlxError(error)) => match error.as_ref() {
            sqlx::Error::Database(error) => {
                assert_eq!(error.code().as_deref(), Some(expected_code));
            }
            error => panic!("unexpected error: {error}"),
        },
        error => panic!("unexpected error: {error}"),
    }
    savepoint.rollback().await.unwrap();
}

#[tokio::test]
#[ignore = "requires API_RS_MIGRATION_TEST_DATABASE_URL pointing to an empty, disposable PostgreSQL database"]
async fn user_uid_and_profile_migration_round_trip() {
    let url = std::env::var("API_RS_MIGRATION_TEST_DATABASE_URL")
        .expect("set API_RS_MIGRATION_TEST_DATABASE_URL");
    let parsed = url::Url::parse(&url).unwrap();
    assert!(
        parsed
            .path()
            .trim_start_matches('/')
            .starts_with("api_rs_migration_test"),
        "use a disposable database named api_rs_migration_test..."
    );
    let db = Database::connect(url).await.unwrap();
    let transaction = db.begin().await.unwrap();
    // Intentionally fail if the table already exists; never replace application data.
    transaction
        .execute_unprepared(
            r#"CREATE TABLE public."user" (
                   id UUID PRIMARY KEY, email VARCHAR NOT NULL UNIQUE, username VARCHAR NULL
               );
               INSERT INTO public."user" (id, email, username) VALUES
                   ('00000000-0000-0000-0000-000000000001', 'alice@example.com', 'alice'),
                   ('00000000-0000-0000-0000-000000000002', 'bob@example.com', 'bob')"#,
        )
        .await
        .unwrap();

    Migrator::up(&transaction, None).await.unwrap();
    let migrated = users(&transaction).await;
    assert_eq!(migrated.len(), 2);
    assert_eq!(migrated[0].id, "00000000-0000-0000-0000-000000000001");
    assert_eq!(migrated[0].email, "alice@example.com");
    assert_eq!(migrated[1].id, "00000000-0000-0000-0000-000000000002");
    assert_eq!(migrated[1].email, "bob@example.com");
    assert!(migrated.iter().all(|user| user.nickname.is_none()));
    assert!(migrated.iter().all(|user| user.locale == "zh-CN"));
    let mut uids: Vec<_> = migrated.iter().map(|user| user.uid).collect();
    uids.sort_unstable();
    assert_eq!(uids, vec![1, 2]);

    // The migration registry makes a second up a no-op, preserving assigned UIDs.
    Migrator::up(&transaction, None).await.unwrap();
    assert_eq!(users(&transaction).await, migrated);
    transaction
        .execute_unprepared(
            r#"INSERT INTO public."user" (id, email, username, nickname, locale) VALUES
                   ('00000000-0000-0000-0000-000000000003', 'carol@example.com', 'carol', '昵称', 'ja-JP')"#,
        )
        .await
        .unwrap();
    let inserted = users(&transaction).await;
    assert_eq!(inserted[2].uid, 3);
    assert_eq!(inserted[2].nickname.as_deref(), Some("昵称"));
    assert_eq!(inserted[2].locale, "ja-JP");

    assert_rejected(
        &transaction,
        r#"INSERT INTO public."user" (id, email, uid) VALUES
               ('00000000-0000-0000-0000-000000000004', 'duplicate@example.com', 1)"#,
        "23505",
    )
    .await;
    assert_rejected(
        &transaction,
        r#"INSERT INTO public."user" (id, email, uid) VALUES
               ('00000000-0000-0000-0000-000000000005', 'null@example.com', NULL)"#,
        "23502",
    )
    .await;

    for (sql, code) in [
        (
            r#"INSERT INTO public."user" (id, email, username) VALUES
               ('00000000-0000-0000-0000-000000000006', 'duplicate-name@example.com', 'alice')"#,
            "23505",
        ),
        (
            r#"UPDATE public."user" SET username = 'alice' WHERE username = 'bob'"#,
            "23505",
        ),
        (
            r#"INSERT INTO public."user" (id, email, uid) VALUES
               ('00000000-0000-0000-0000-000000000007', 'zero@example.com', 0)"#,
            "23514",
        ),
        (
            r#"INSERT INTO public."user" (id, email, uid) VALUES
               ('00000000-0000-0000-0000-000000000008', 'negative@example.com', -1)"#,
            "23514",
        ),
        (
            r#"UPDATE public."user" SET locale = 'unsupported' WHERE username = 'alice'"#,
            "23514",
        ),
        (
            r#"UPDATE public."user" SET locale = NULL WHERE username = 'alice'"#,
            "23502",
        ),
    ] {
        assert_rejected(&transaction, sql, code).await;
    }

    // Nullable usernames follow ordinary PostgreSQL UNIQUE semantics. Case is
    // preserved, so a distinct "Alice" does not collide with "alice".
    transaction
        .execute_unprepared(
            r#"INSERT INTO public."user" (id, email, username) VALUES
                   ('00000000-0000-0000-0000-000000000009', 'null-one@example.com', NULL),
                   ('00000000-0000-0000-0000-00000000000a', 'null-two@example.com', NULL),
                   ('00000000-0000-0000-0000-00000000000b', 'case@example.com', 'Alice')"#,
        )
        .await
        .unwrap();
    let inserted = users(&transaction).await;
    assert_eq!(
        inserted
            .iter()
            .filter(|user| user.username.is_none())
            .count(),
        2
    );

    Migrator::down(&transaction, Some(1)).await.unwrap();
    let rolled_back = transaction
        .query_one_raw(Statement::from_string(
            DbBackend::Postgres,
            r#"SELECT
                 (SELECT count(*) FROM public."user") AS user_count,
                 (SELECT count(*) FROM information_schema.columns
                  WHERE table_schema = 'public' AND table_name = 'user'
                    AND column_name IN ('uid', 'nickname', 'locale')) AS removed_columns,
                 to_regclass('public.user_uid_seq') IS NULL AS sequence_removed,
                 (SELECT string_agg(id::text || ':' || email, ',' ORDER BY email)
                  FROM public."user") AS original_data"#,
        ))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(rolled_back.try_get::<i64>("", "user_count").unwrap(), 6);
    assert_eq!(
        rolled_back.try_get::<i64>("", "removed_columns").unwrap(),
        0
    );
    assert!(rolled_back.try_get::<bool>("", "sequence_removed").unwrap());
    let expected_data = inserted
        .iter()
        .map(|user| format!("{}:{}", user.id, user.email))
        .collect::<Vec<_>>()
        .join(",");
    assert_eq!(
        rolled_back.try_get::<String>("", "original_data").unwrap(),
        expected_data
    );

    // Reapplying also works for an empty table and creates a fresh identity sequence.
    transaction
        .execute_unprepared(r#"DELETE FROM public."user""#)
        .await
        .unwrap();
    Migrator::up(&transaction, None).await.unwrap();
    transaction
        .execute_unprepared(
            r#"INSERT INTO public."user" (id, email) VALUES
                   ('00000000-0000-0000-0000-000000000001', 'alice@example.com')"#,
        )
        .await
        .unwrap();
    let reapplied = users(&transaction).await;
    assert_eq!(reapplied[0].uid, 1);
    assert_eq!(reapplied[0].nickname, None);
    assert_eq!(reapplied[0].locale, "zh-CN");

    transaction.rollback().await.unwrap();

    // Duplicate pre-existing usernames must fail atomically, rather than
    // renaming users or leaving half of the new schema behind.
    let transaction = db.begin().await.unwrap();
    transaction
        .execute_unprepared(
            r#"CREATE TABLE public."user" (
                   id UUID PRIMARY KEY, email VARCHAR NOT NULL UNIQUE, username VARCHAR NULL
               );
               INSERT INTO public."user" (id, email, username) VALUES
                   ('00000000-0000-0000-0000-000000000001', 'alice@example.com', 'same'),
                   ('00000000-0000-0000-0000-000000000002', 'bob@example.com', 'same')"#,
        )
        .await
        .unwrap();
    let attempt = transaction.begin().await.unwrap();
    assert!(Migrator::up(&attempt, None).await.is_err());
    attempt.rollback().await.unwrap();
    let unchanged = transaction
        .query_one_raw(Statement::from_string(
            DbBackend::Postgres,
            r#"SELECT
                 (SELECT count(*) FROM public."user" WHERE username = 'same') AS user_count,
                 (SELECT count(*) FROM information_schema.columns
                  WHERE table_schema = 'public' AND table_name = 'user'
                    AND column_name IN ('uid', 'nickname', 'locale')) AS added_columns"#,
        ))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(unchanged.try_get::<i64>("", "user_count").unwrap(), 2);
    assert_eq!(unchanged.try_get::<i64>("", "added_columns").unwrap(), 0);
    transaction.rollback().await.unwrap();
    db.close().await.unwrap();
}
