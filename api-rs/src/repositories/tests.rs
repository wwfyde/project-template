use std::sync::Arc;

use chrono::{TimeZone, Utc};
use sea_orm::{ConnectOptions, ConnectionTrait, Database, DatabaseConnection, Schema};
use sqlx::postgres::PgPoolOptions;
use uuid::Uuid;

use super::RepositoryError;
use crate::entities;
use crate::models::Locale;
use crate::models::student::{NewStudent, Student, StudentRepository};
use crate::models::todo::{Todo, TodoRepository};
use crate::models::user::{User, UserId, UserQuery, UserRepository, UserSort, UserWrite};

use super::memory::{InMemoryStudentRepository, InMemoryTodoRepository, InMemoryUserRepository};
use super::orm::{SeaOrmStudentRepository, SeaOrmTodoRepository, SeaOrmUserRepository};
use super::sqlx::{SqlxStudentRepository, SqlxTodoRepository, SqlxUserRepository};

async fn create_tables(db: &DatabaseConnection) {
    // Intentionally fail if tables already exist: use an empty, disposable database.
    let schema = Schema::new(db.get_database_backend());
    for statement in [
        super::orm::user::user_table_for_tests(db.get_database_backend()),
        schema.create_table_from_entity(entities::student::Entity),
        schema.create_table_from_entity(entities::todo::Entity),
    ] {
        db.execute(&statement).await.unwrap();
    }
}

async fn sqlite_database() -> Arc<DatabaseConnection> {
    let mut options = ConnectOptions::new("sqlite::memory:");
    options.max_connections(1);
    let db = Database::connect(options).await.unwrap();
    db.execute_unprepared("ATTACH DATABASE ':memory:' AS public")
        .await
        .unwrap();
    create_tables(&db).await;
    Arc::new(db)
}

fn user(id: u128, email: &str) -> UserWrite {
    UserWrite {
        id: UserId(Uuid::from_u128(id)),
        email: Some(email.into()),
        nickname: Some(format!("用户 {id}")),
        username: Some(format!("O'Reilly'; -- {id}")),
        hashed_password: Some("test-hash".into()),
        is_active: Some(true),
        locale: Locale::JaJp,
        is_superuser: Some(false),
        created_at: Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
        updated_at: None,
    }
}

fn assert_written(saved: &User, input: &UserWrite, created_at: chrono::DateTime<Utc>) {
    let mut expected = input.clone();
    expected.created_at = created_at;
    assert_eq!(UserWrite::from(saved), expected);
    assert!(saved.uid.0 > 0);
    assert!(saved.uid.0 <= i64::MAX as u64);
}

async fn user_contract(repo: &dyn UserRepository) {
    assert!(repo.find_all().await.unwrap().is_empty());
    assert!(!repo.exists_by_id(UserId(Uuid::nil())).await.unwrap());
    let first_input = user(10, "first@example.com");
    let second_input = user(20, "o'reilly@example.com");
    // Insert out of order to check stable UUID ordering independently of UID allocation.
    let second = repo.insert(&second_input).await.unwrap();
    let first = repo.insert(&first_input).await.unwrap();
    assert_written(&first, &first_input, first_input.created_at);
    assert_written(&second, &second_input, second_input.created_at);
    assert_ne!(first.uid, second.uid);
    assert!(repo.exists_by_id(first.id.clone()).await.unwrap());
    assert_eq!(
        repo.find_all().await.unwrap(),
        vec![first.clone(), second.clone()]
    );
    assert_eq!(
        repo.find_by_id(first.id.clone()).await.unwrap(),
        Some(first.clone())
    );
    assert_eq!(
        repo.find_by_email("o'reilly@example.com").await.unwrap(),
        Some(second.clone())
    );
    assert!(repo.find_by_email("' OR TRUE --").await.unwrap().is_none());
    assert!(
        repo.find_by_id(UserId(Uuid::nil()))
            .await
            .unwrap()
            .is_none()
    );

    expect_conflict(repo.insert(&first_input).await);
    let mut duplicate_email = user(30, "first@example.com");
    expect_conflict(repo.insert(&duplicate_email).await);
    duplicate_email.email = None;
    expect_invalid(repo.insert(&duplicate_email).await);
    let mut invalid_update = UserWrite::from(&first);
    invalid_update.email = None;
    expect_invalid(repo.update(&invalid_update).await);
    invalid_update.email = second.email.clone();
    expect_conflict(repo.update(&invalid_update).await);
    assert_eq!(
        repo.find_by_id(first.id.clone()).await.unwrap(),
        Some(first.clone())
    );

    let mut update = UserWrite::from(&first);
    update.email = Some("updated@example.com".into());
    update.nickname = None;
    update.username = None;
    update.locale = Locale::EnUs;
    update.hashed_password = None;
    update.is_active = None;
    update.is_superuser = None;
    update.created_at += chrono::Duration::days(1);
    update.updated_at = Some(update.created_at);
    let updated = repo.update(&update).await.unwrap();
    assert_written(&updated, &update, first.created_at);
    assert_eq!(
        updated.uid, first.uid,
        "updates must preserve the generated UID"
    );
    assert_eq!(
        repo.find_by_id(first.id.clone()).await.unwrap(),
        Some(updated.clone())
    );
    assert!(
        repo.find_by_email("first@example.com")
            .await
            .unwrap()
            .is_none()
    );
    assert_eq!(
        repo.find_by_email("updated@example.com").await.unwrap(),
        Some(updated)
    );

    repo.delete_by_id(first.id.clone()).await.unwrap();
    assert!(!repo.exists_by_id(first.id.clone()).await.unwrap());
    assert!(repo.find_by_id(first.id.clone()).await.unwrap().is_none());
    assert!(matches!(
        repo.update(&first_input).await,
        Err(error) if matches!(error.downcast_ref::<RepositoryError>(), Some(RepositoryError::NotFound))
    ));
    assert!(matches!(
        repo.delete_by_id(first.id).await,
        Err(error) if matches!(error.downcast_ref::<RepositoryError>(), Some(RepositoryError::NotFound))
    ));
    repo.delete_by_id(second.id).await.unwrap();
    assert!(repo.find_all().await.unwrap().is_empty());
    user_bulk_save_contract(repo).await;
    user_username_contract(repo).await;
    user_search_contract(repo).await;
}

fn expect_invalid<T: std::fmt::Debug>(result: anyhow::Result<T>) {
    let error = result.unwrap_err();
    assert!(
        matches!(
            error.downcast_ref::<RepositoryError>(),
            Some(RepositoryError::InvalidInput(_))
        ),
        "{error:#}"
    );
}

fn expect_conflict<T: std::fmt::Debug>(result: anyhow::Result<T>) {
    let error = result.unwrap_err();
    assert!(
        matches!(
            error.downcast_ref::<RepositoryError>(),
            Some(RepositoryError::Conflict)
        ),
        "{error:#}"
    );
}

async fn user_bulk_save_contract(repo: &dyn UserRepository) {
    assert!(repo.find_many(&[]).await.unwrap().is_empty());
    let first_input = user(10, "first-save@example.com");
    let second_input = user(20, "second-save@example.com");
    let second = repo.save(&second_input).await.unwrap();
    let first = repo.save(&first_input).await.unwrap();
    assert_written(&first, &first_input, first_input.created_at);
    assert_written(&second, &second_input, second_input.created_at);
    assert_ne!(first.uid, second.uid);

    let mut update = UserWrite::from(&first);
    update.email = Some("changed@example.com".into());
    update.nickname = Some("Updated nickname".into());
    update.username = None;
    update.locale = Locale::EnUs;
    update.hashed_password = None;
    update.is_active = None;
    update.is_superuser = None;
    update.created_at += chrono::Duration::days(1);
    update.updated_at = Some(update.created_at);
    let updated = repo.save(&update).await.unwrap();
    assert_written(&updated, &update, first.created_at);
    assert_eq!(
        updated.uid, first.uid,
        "upserts must preserve the existing UID"
    );
    assert_eq!(
        repo.save(&UserWrite::from(&updated)).await.unwrap(),
        updated
    );
    assert_eq!(
        repo.find_by_id(first.id.clone()).await.unwrap(),
        Some(updated.clone())
    );
    assert!(
        repo.find_by_email("first-save@example.com")
            .await
            .unwrap()
            .is_none()
    );
    expect_conflict(repo.insert(&UserWrite::from(&updated)).await);

    let mut conflict = UserWrite::from(&second);
    conflict.email = updated.email.clone();
    expect_conflict(repo.save(&conflict).await);
    conflict.id = UserId(Uuid::from_u128(30));
    expect_conflict(repo.save(&conflict).await);
    assert_eq!(
        repo.find_by_id(second.id.clone()).await.unwrap(),
        Some(second.clone())
    );
    assert!(
        repo.find_by_id(conflict.id.clone())
            .await
            .unwrap()
            .is_none()
    );
    conflict.email = None;
    expect_invalid(repo.save(&conflict).await);

    assert_eq!(
        repo.find_many(&[
            second.id.clone(),
            UserId(Uuid::nil()),
            first.id.clone(),
            second.id.clone()
        ])
        .await
        .unwrap(),
        vec![updated.clone(), second.clone()]
    );
    assert_eq!(
        repo.find_many(&vec![first.id.clone(); 1000]).await.unwrap(),
        vec![updated]
    );
    expect_invalid(repo.find_many(&vec![first.id.clone(); 1001]).await);
    repo.delete_by_id(first.id).await.unwrap();
    repo.delete_by_id(second.id).await.unwrap();
}

async fn user_username_contract(repo: &dyn UserRepository) {
    let mut first_input = user(60, "first-name@example.com");
    first_input.username = Some("CaseName".into());
    let first = repo.insert(&first_input).await.unwrap();
    let second_input = user(61, "second-name@example.com");
    let second = repo.insert(&second_input).await.unwrap();
    let mut conflict = user(62, "new-name@example.com");
    conflict.username = first.username.clone();
    expect_conflict(repo.insert(&conflict).await);
    expect_conflict(repo.save(&conflict).await);
    assert!(
        repo.find_by_id(conflict.id.clone())
            .await
            .unwrap()
            .is_none()
    );

    let mut update = UserWrite::from(&second);
    update.username = first.username.clone();
    update.nickname = Some("must not be written".into());
    update.locale = Locale::EnUs;
    expect_conflict(repo.update(&update).await);
    expect_conflict(repo.save(&update).await);
    assert_eq!(
        repo.find_by_id(second.id.clone()).await.unwrap(),
        Some(second.clone())
    );
    assert_eq!(
        repo.find_by_id(first.id.clone()).await.unwrap(),
        Some(first.clone())
    );

    // Uniqueness is case-sensitive, and more than one NULL username is permitted.
    conflict.username = Some("casename".into());
    let third = repo.insert(&conflict).await.unwrap();
    assert_ne!(third.uid, first.uid);
    let mut first_null = UserWrite::from(&first);
    first_null.username = None;
    let first_null = repo.update(&first_null).await.unwrap();
    let mut second_null = UserWrite::from(&second);
    second_null.username = None;
    let second_null = repo.save(&second_null).await.unwrap();
    assert_eq!(first_null.uid, first.uid);
    assert_eq!(second_null.uid, second.uid);
    assert_eq!(first_null.username, None);
    assert_eq!(second_null.username, None);

    let mut fourth_input = user(63, "null-name@example.com");
    fourth_input.username = None;
    let fourth = repo.insert(&fourth_input).await.unwrap();
    for saved in [first_null, second_null, third, fourth] {
        repo.delete_by_id(saved.id).await.unwrap();
    }
    assert!(repo.find_all().await.unwrap().is_empty());
}

async fn user_search_contract(repo: &dyn UserRepository) {
    let mut alice = user(101, "Alice@example.com");
    alice.username = Some("Alpha_100%!\\'".into());
    let mut bob = user(102, "bob@example.com");
    bob.username = Some("BETA".into());
    bob.is_active = Some(false);
    bob.is_superuser = Some(true);
    bob.created_at -= chrono::Duration::days(1);
    let mut nulls = user(103, "charlie@example.com");
    nulls.username = None;
    nulls.is_active = None;
    nulls.is_superuser = None;
    let mut lookalike = user(104, "other@example.com");
    lookalike.username = Some("alphaX100xZ".into());
    lookalike.is_superuser = Some(true);
    let mut chinese = user(105, "中文@example.com");
    chinese.username = Some("中文用户".into());
    chinese.created_at += chrono::Duration::days(1);
    for item in [&chinese, &bob, &lookalike, &alice, &nulls] {
        repo.insert(item).await.unwrap();
    }

    let cases = [
        (UserQuery::default(), vec![101, 102, 103, 104, 105]),
        (
            UserQuery {
                keyword: Some("  ALPHA_100%!  ".into()),
                ..Default::default()
            },
            vec![101],
        ),
        (
            UserQuery {
                keyword: Some("\\'".into()),
                ..Default::default()
            },
            vec![101],
        ),
        (
            UserQuery {
                keyword: Some(" ALICE@EXAMPLE.COM ".into()),
                ..Default::default()
            },
            vec![101],
        ),
        (
            UserQuery {
                keyword: Some("中文".into()),
                ..Default::default()
            },
            vec![105],
        ),
        (
            UserQuery {
                keyword: Some("' OR TRUE --".into()),
                ..Default::default()
            },
            vec![],
        ),
        (
            UserQuery {
                keyword: Some(" \t ".into()),
                ..Default::default()
            },
            vec![101, 102, 103, 104, 105],
        ),
        (
            UserQuery {
                is_active: Some(false),
                ..Default::default()
            },
            vec![102],
        ),
        (
            UserQuery {
                is_superuser: Some(false),
                ..Default::default()
            },
            vec![101, 105],
        ),
        (
            UserQuery {
                is_active: Some(true),
                is_superuser: Some(true),
                ..Default::default()
            },
            vec![104],
        ),
        (
            UserQuery {
                keyword: Some("alpha".into()),
                is_superuser: Some(true),
                ..Default::default()
            },
            vec![104],
        ),
        (
            UserQuery {
                sort: UserSort::IdDesc,
                ..Default::default()
            },
            vec![105, 104, 103, 102, 101],
        ),
        (
            UserQuery {
                sort: UserSort::CreatedAtAsc,
                ..Default::default()
            },
            vec![102, 101, 103, 104, 105],
        ),
        (
            UserQuery {
                sort: UserSort::CreatedAtDesc,
                ..Default::default()
            },
            vec![105, 104, 103, 101, 102],
        ),
    ];
    for (query, ids) in cases {
        let page = repo.search(&query).await.unwrap();
        assert_eq!(page.total, ids.len() as u64, "{query:?}");
        assert_eq!(page.page, query.page);
        assert_eq!(page.page_size, query.page_size);
        assert_eq!(
            page.items
                .iter()
                .map(|user| user.id.0.as_u128())
                .collect::<Vec<_>>(),
            ids,
            "{query:?}"
        );
    }
    for (number, ids) in [
        (1, vec![101, 102]),
        (2, vec![103, 104]),
        (3, vec![105]),
        (4, vec![]),
    ] {
        let query = UserQuery {
            page: number,
            page_size: 2,
            ..Default::default()
        };
        let page = repo.search(&query).await.unwrap();
        assert_eq!(page.total, 5);
        assert_eq!(
            page.items
                .iter()
                .map(|user| user.id.0.as_u128())
                .collect::<Vec<_>>(),
            ids
        );
    }
    let page = repo
        .search(&UserQuery {
            page: i64::MAX as u64 + 1,
            page_size: 1,
            ..Default::default()
        })
        .await
        .unwrap();
    assert_eq!(page.total, 5);
    assert!(page.items.is_empty());
    for (number, size) in [
        (0, 20),
        (1, 0),
        (1, 101),
        (u64::MAX, 100),
        (i64::MAX as u64 + 2, 1),
    ] {
        expect_invalid(
            repo.search(&UserQuery {
                page: number,
                page_size: size,
                ..Default::default()
            })
            .await,
        );
    }
    for item in [alice, bob, nulls, lookalike, chinese] {
        repo.delete_by_id(item.id).await.unwrap();
    }
    let empty = repo.search(&UserQuery::default()).await.unwrap();
    assert_eq!(empty.total, 0);
    assert!(empty.items.is_empty());
}

async fn concurrent_user_save_contract(repo: Arc<dyn UserRepository>) {
    let input = user(500, "concurrent-save@example.com");
    let barrier = Arc::new(tokio::sync::Barrier::new(8));
    let mut tasks = tokio::task::JoinSet::new();
    for index in 0..8 {
        let repo = repo.clone();
        let barrier = barrier.clone();
        let mut user = input.clone();
        user.username = Some(format!("Save {index}"));
        tasks.spawn(async move {
            barrier.wait().await;
            repo.save(&user).await.unwrap()
        });
    }
    let mut generated_uids = std::collections::BTreeSet::new();
    while let Some(result) = tasks.join_next().await {
        let saved = result.unwrap();
        assert_eq!(saved.id, input.id);
        assert_eq!(saved.created_at, input.created_at);
        assert!(saved.uid.0 > 0);
        generated_uids.insert(saved.uid.0);
    }
    assert_eq!(generated_uids.len(), 1, "concurrent upserts retain one UID");
    assert_eq!(
        repo.find_many(std::slice::from_ref(&input.id))
            .await
            .unwrap()
            .len(),
        1
    );
    repo.delete_by_id(input.id).await.unwrap();
}

async fn student_contract(repo: &dyn StudentRepository) {
    assert!(repo.find_all().await.unwrap().is_empty());
    let first = repo
        .create(&NewStudent {
            name: "O'Reilly'; --".into(),
            age: 18,
        })
        .await
        .unwrap();
    let second = repo
        .create(&NewStudent {
            name: "Alice".into(),
            age: 20,
        })
        .await
        .unwrap();
    assert!(first.id > 0);
    assert!(second.id > first.id);
    assert_eq!(first.name, "O'Reilly'; --");
    assert_eq!(first.age, 18);
    assert_eq!(
        repo.find_all().await.unwrap(),
        vec![first.clone(), second.clone()]
    );
    assert_eq!(
        repo.find_by_id(first.id).await.unwrap(),
        Some(first.clone())
    );
    assert!(repo.find_by_id(-1).await.unwrap().is_none());
    let update = Student {
        id: first.id,
        name: "Updated student".into(),
        age: 21,
    };
    assert_eq!(repo.update(&update).await.unwrap(), update);
    assert_eq!(
        repo.find_by_id(first.id).await.unwrap(),
        Some(update.clone())
    );
    repo.delete_by_id(first.id).await.unwrap();
    assert!(repo.find_by_id(first.id).await.unwrap().is_none());
    assert!(matches!(
        repo.update(&update).await,
        Err(error) if matches!(error.downcast_ref::<RepositoryError>(), Some(RepositoryError::NotFound))
    ));
    assert!(matches!(
        repo.delete_by_id(first.id).await,
        Err(error) if matches!(error.downcast_ref::<RepositoryError>(), Some(RepositoryError::NotFound))
    ));
    repo.delete_by_id(second.id).await.unwrap();
    assert!(repo.find_all().await.unwrap().is_empty());

    let next = repo
        .create(&NewStudent {
            name: "After deletion".into(),
            age: 22,
        })
        .await
        .unwrap();
    assert!(
        next.id > second.id,
        "deleting records must not reuse student IDs"
    );
    repo.delete_by_id(next.id).await.unwrap();
}

fn todo(id: u128, completed: Option<bool>) -> Todo {
    let now = Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap();
    Todo {
        id: Uuid::from_u128(id),
        title: "Buy O'Reilly's book'; --".into(),
        completed,
        created_at: now,
        updated_at: now,
    }
}

async fn todo_contract(repo: &dyn TodoRepository) {
    assert!(repo.find_all().await.unwrap().is_empty());
    let first = todo(10, Some(false));
    let second = todo(20, None);
    assert_eq!(repo.create(&second).await.unwrap(), second);
    assert_eq!(repo.create(&first).await.unwrap(), first);
    assert_eq!(
        repo.find_all().await.unwrap(),
        vec![first.clone(), second.clone()]
    );
    assert_eq!(
        repo.find_by_id(first.id).await.unwrap(),
        Some(first.clone())
    );
    assert!(repo.find_by_id(Uuid::nil()).await.unwrap().is_none());
    assert!(matches!(
        repo.create(&first).await,
        Err(error) if matches!(error.downcast_ref::<RepositoryError>(), Some(RepositoryError::Conflict))
    ));

    let mut update = first.clone();
    update.title = "Done".into();
    update.completed = Some(true);
    update.created_at += chrono::Duration::days(1);
    update.updated_at = update.created_at;
    let mut expected = update.clone();
    expected.created_at = first.created_at;
    assert_eq!(repo.update(&update).await.unwrap(), expected);
    assert_eq!(
        repo.find_by_id(first.id).await.unwrap(),
        Some(expected.clone())
    );
    update.completed = None;
    expected.completed = None;
    assert_eq!(repo.update(&update).await.unwrap(), expected);
    assert_eq!(repo.find_by_id(first.id).await.unwrap(), Some(expected));

    repo.delete_by_id(first.id).await.unwrap();
    assert!(repo.find_by_id(first.id).await.unwrap().is_none());
    assert!(matches!(
        repo.update(&update).await,
        Err(error) if matches!(error.downcast_ref::<RepositoryError>(), Some(RepositoryError::NotFound))
    ));
    assert!(matches!(
        repo.delete_by_id(first.id).await,
        Err(error) if matches!(error.downcast_ref::<RepositoryError>(), Some(RepositoryError::NotFound))
    ));
    repo.delete_by_id(second.id).await.unwrap();
    assert!(repo.find_all().await.unwrap().is_empty());
}

#[tokio::test]
async fn sea_orm_user_contract() {
    user_contract(&SeaOrmUserRepository::new(sqlite_database().await)).await;
}

#[tokio::test]
async fn sea_orm_student_contract() {
    student_contract(&SeaOrmStudentRepository::new(sqlite_database().await)).await;
}

#[tokio::test]
async fn sea_orm_todo_contract() {
    todo_contract(&SeaOrmTodoRepository::new(sqlite_database().await)).await;
}

#[tokio::test]
async fn in_memory_user_contract() {
    user_contract(&InMemoryUserRepository::default()).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn in_memory_user_save_is_atomic() {
    concurrent_user_save_contract(Arc::new(InMemoryUserRepository::default())).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn in_memory_user_uids_are_atomic_and_never_reused_after_deletion() {
    let repo = InMemoryUserRepository::default();
    let barrier = Arc::new(tokio::sync::Barrier::new(16));
    let mut tasks = tokio::task::JoinSet::new();
    for index in 0..16_u128 {
        let repo = repo.clone();
        let barrier = barrier.clone();
        tasks.spawn(async move {
            barrier.wait().await;
            repo.insert(&user(800 + index, &format!("uid-{index}@example.com")))
                .await
                .unwrap()
        });
    }
    let mut uids = std::collections::BTreeSet::new();
    let mut users = Vec::new();
    while let Some(result) = tasks.join_next().await {
        let saved = result.unwrap();
        assert!(uids.insert(saved.uid.0), "generated UIDs must be unique");
        users.push(saved);
    }
    assert_eq!(uids, (1..=16).collect());
    for saved in users {
        repo.delete_by_id(saved.id).await.unwrap();
    }
    let next = repo
        .insert(&user(1000, "after-delete@example.com"))
        .await
        .unwrap();
    assert!(
        next.uid.0 > *uids.last().unwrap(),
        "deleted UIDs cannot be reused"
    );
}

#[tokio::test]
async fn in_memory_student_contract() {
    student_contract(&InMemoryStudentRepository::default()).await;
}

#[tokio::test]
async fn in_memory_todo_contract() {
    todo_contract(&InMemoryTodoRepository::default()).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn in_memory_student_clones_share_an_atomic_id_sequence() {
    let repo = InMemoryStudentRepository::default();
    let barrier = Arc::new(tokio::sync::Barrier::new(16));
    let mut tasks = tokio::task::JoinSet::new();
    for index in 0..16 {
        let repo = repo.clone();
        let barrier = barrier.clone();
        tasks.spawn(async move {
            barrier.wait().await;
            repo.create(&NewStudent {
                name: format!("Student {index}"),
                age: 20,
            })
            .await
            .unwrap()
            .id
        });
    }
    let mut ids = std::collections::BTreeSet::new();
    while let Some(result) = tasks.join_next().await {
        assert!(ids.insert(result.unwrap()), "IDs must be unique");
    }
    assert_eq!(ids, (1..=16).collect());
    assert_eq!(repo.find_all().await.unwrap().len(), 16);
}

#[tokio::test]
#[ignore = "requires API_RS_TEST_DATABASE_URL pointing to an empty, disposable PostgreSQL database"]
async fn postgres_repository_contracts() {
    let url = std::env::var("API_RS_TEST_DATABASE_URL").expect("set API_RS_TEST_DATABASE_URL");
    let pool = PgPoolOptions::new()
        .max_connections(3)
        .connect(&url)
        .await
        .unwrap();
    let db = Arc::new(DatabaseConnection::from(pool.clone()));
    create_tables(&db).await;

    user_contract(&SqlxUserRepository::new(pool.clone())).await;
    user_contract(&SeaOrmUserRepository::new(db.clone())).await;
    concurrent_user_save_contract(Arc::new(SqlxUserRepository::new(pool.clone()))).await;
    concurrent_user_save_contract(Arc::new(SeaOrmUserRepository::new(db.clone()))).await;
    student_contract(&SqlxStudentRepository::new(pool.clone())).await;
    student_contract(&SeaOrmStudentRepository::new(db.clone())).await;
    todo_contract(&SqlxTodoRepository::new(pool.clone())).await;
    todo_contract(&SeaOrmTodoRepository::new(db.clone())).await;

    // A shared pool also permits switching adapters without copying data.
    let sqlx_users = SqlxUserRepository::new(pool.clone());
    let orm_users = SeaOrmUserRepository::new(db);
    let shared_input = user(50, "shared@example.com");
    let shared = sqlx_users.insert(&shared_input).await.unwrap();
    let sqlx_conflict = sqlx_users.insert(&shared_input).await.unwrap_err();
    assert!(matches!(
        sqlx_conflict.downcast_ref::<::sqlx::Error>(),
        Some(::sqlx::Error::Database(_))
    ));
    assert!(matches!(
        sqlx_conflict.downcast_ref::<RepositoryError>(),
        Some(RepositoryError::Conflict)
    ));
    let orm_conflict = orm_users.insert(&shared_input).await.unwrap_err();
    assert!(orm_conflict.downcast_ref::<sea_orm::DbErr>().is_some());
    assert!(matches!(
        orm_conflict.downcast_ref::<RepositoryError>(),
        Some(RepositoryError::Conflict)
    ));
    assert_eq!(
        orm_users.find_by_id(shared.id.clone()).await.unwrap(),
        Some(shared.clone())
    );
    orm_users.delete_by_id(shared.id.clone()).await.unwrap();
    assert!(sqlx_users.find_by_id(shared.id).await.unwrap().is_none());
    pool.close().await;
}
