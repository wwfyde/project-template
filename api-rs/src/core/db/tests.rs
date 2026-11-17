use super::sync_schema;
use crate::entities::{account, account_member, tenant, tenant_member, user};
use sea_orm::{
    ActiveModelTrait, ConnectionTrait, Database, DatabaseConnection, DbBackend, EntityTrait,
    IntoActiveModel, QueryOrder, Set, SqlErr, Statement,
};
use uuid::Uuid;

async fn table_names(db: &DatabaseConnection) -> Vec<String> {
    db.query_all_raw(Statement::from_string(
        DbBackend::Postgres,
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename",
    ))
    .await
    .unwrap()
    .into_iter()
    .map(|row| row.try_get("", "tablename").unwrap())
    .collect()
}

async fn users(db: &DatabaseConnection) -> Vec<user::Model> {
    user::Entity::find()
        .order_by_asc(user::Column::Id)
        .all(db)
        .await
        .unwrap()
}

fn new_user(email: &str) -> user::ActiveModel {
    user::ActiveModel {
        id: Set(Uuid::now_v7()),
        email: Set(email.to_owned()),
        created_at: Set(chrono::Utc::now().into()),
        ..Default::default()
    }
}

#[tokio::test]
#[ignore = "requires API_RS_SCHEMA_TEST_DATABASE_URL pointing to an empty, disposable PostgreSQL database"]
async fn entity_first_schema_sync_creates_and_updates_tables() {
    let url = std::env::var("API_RS_SCHEMA_TEST_DATABASE_URL")
        .expect("set API_RS_SCHEMA_TEST_DATABASE_URL");
    let parsed = url::Url::parse(&url).unwrap();
    assert!(
        parsed
            .path()
            .trim_start_matches('/')
            .starts_with("api_rs_schema_test"),
        "use a disposable database named api_rs_schema_test..."
    );
    let db = Database::connect(url).await.unwrap();
    // The test may alter only tables that it creates in this empty database.
    assert!(table_names(&db).await.is_empty());

    sync_schema(&db).await.unwrap();
    assert_eq!(
        table_names(&db).await,
        [
            "account",
            "account_member",
            "author",
            "book",
            "book_author",
            "course",
            "item",
            "llm",
            "order",
            "student",
            "student_course",
            "tenant",
            "tenant_member",
            "todo",
            "user",
        ]
    );
    let mut first_input = new_user("first@example.com");
    first_input.username = Set(Some("alice".to_owned()));
    let first = first_input.insert(&db).await.unwrap();
    let second = new_user("second@example.com").insert(&db).await.unwrap();
    assert_eq!((first.uid, second.uid), (1, 2));
    assert_eq!(first.nickname, None);
    assert_eq!(second.nickname, None);
    assert_eq!(first.locale, "zh-CN");
    assert_eq!(second.locale, "zh-CN");
    let original = users(&db).await;

    sync_schema(&db).await.unwrap();
    assert_eq!(users(&db).await, original);
    let mut duplicate = new_user("duplicate@example.com");
    duplicate.uid = Set(first.uid);
    assert!(matches!(
        duplicate.insert(&db).await.unwrap_err().sql_err(),
        Some(SqlErr::UniqueConstraintViolation(_))
    ));

    let mut duplicate = new_user("duplicate-name@example.com");
    duplicate.username = Set(first.username.clone());
    assert!(matches!(
        duplicate.insert(&db).await.unwrap_err().sql_err(),
        Some(SqlErr::UniqueConstraintViolation(_))
    ));
    assert_check_rejected(
        &db,
        r#"UPDATE public."user" SET uid = 0 WHERE username = 'alice'"#,
    )
    .await;
    assert_check_rejected(
        &db,
        r#"UPDATE public."user" SET locale = 'invalid' WHERE username = 'alice'"#,
    )
    .await;

    // Missing fields and a missing uniqueness constraint are restored by sync.
    db.execute_unprepared(
        r#"ALTER TABLE public."user"
           DROP CONSTRAINT user_username_key,
           DROP COLUMN nickname, DROP COLUMN locale, DROP COLUMN uid"#,
    )
    .await
    .unwrap();
    sync_schema(&db).await.unwrap();
    let backfilled = users(&db).await;
    assert_eq!(backfilled.len(), original.len());
    for (before, after) in original.iter().zip(&backfilled) {
        assert_eq!(after.id, before.id);
        assert_eq!(after.email, before.email);
        assert_eq!(after.created_at, before.created_at);
        assert!(after.uid > 0);
        assert_eq!(after.nickname, None);
        assert_eq!(after.locale, "zh-CN");
    }
    assert_ne!(backfilled[0].uid, backfilled[1].uid);
    let previous_max = backfilled.iter().map(|user| user.uid).max().unwrap();
    let third = new_user("third@example.com").insert(&db).await.unwrap();
    assert!(third.uid > previous_max);
    let mut update = third.into_active_model();
    update.nickname = Set(Some("昵称".to_owned()));
    update.locale = Set("en-US".to_owned());
    let updated = update.update(&db).await.unwrap();

    sync_schema(&db).await.unwrap();
    assert_eq!(
        user::Entity::find_by_id(updated.id).one(&db).await.unwrap(),
        Some(updated)
    );
    let mut duplicate = new_user("still-duplicate@example.com");
    duplicate.username = Set(Some("alice".to_owned()));
    assert!(matches!(
        duplicate.insert(&db).await.unwrap_err().sql_err(),
        Some(SqlErr::UniqueConstraintViolation(_))
    ));
    // Second and third users both have NULL usernames; a distinct case is legal.
    let mut different_case = new_user("case@example.com");
    different_case.username = Set(Some("Alice".to_owned()));
    different_case.insert(&db).await.unwrap();
    assert_check_rejected(
        &db,
        r#"UPDATE public."user" SET uid = -1 WHERE username = 'alice'"#,
    )
    .await;
    assert_check_rejected(
        &db,
        r#"UPDATE public."user" SET locale = 'invalid' WHERE username = 'alice'"#,
    )
    .await;
    tenancy_schema_contract(&db, first.id, second.id).await;
    let foreign_keys = db
        .query_one_raw(Statement::from_string(
            DbBackend::Postgres,
            "SELECT count(*) AS count FROM pg_constraint
             WHERE connamespace = 'public'::regnamespace AND contype = 'f'
               AND conrelid IN ('public.tenant'::regclass, 'public.account'::regclass,
                                'public.tenant_member'::regclass, 'public.account_member'::regclass)",
        ))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(foreign_keys.try_get::<i64>("", "count").unwrap(), 7);
    db.close().await.unwrap();
}

async fn tenancy_schema_contract(db: &DatabaseConnection, first_user: Uuid, second_user: Uuid) {
    let at = chrono::Utc::now();
    let personal = tenant::ActiveModel {
        id: Set(Uuid::now_v7()),
        name: Set("Personal".into()),
        kind: Set("personal".into()),
        personal_user_id: Set(Some(first_user)),
        created_at: Set(at.into()),
        ..Default::default()
    }
    .insert(db)
    .await
    .unwrap();
    assert!(personal.is_active);
    let organization = tenant::ActiveModel {
        id: Set(Uuid::now_v7()),
        name: Set("Organization".into()),
        kind: Set("organization".into()),
        personal_user_id: Set(None),
        created_at: Set(at.into()),
        ..Default::default()
    }
    .insert(db)
    .await
    .unwrap();
    let personal_account = account::ActiveModel {
        id: Set(Uuid::now_v7()),
        tenant_id: Set(personal.id),
        name: Set("Personal account".into()),
        kind: Set("personal".into()),
        personal_user_id: Set(Some(first_user)),
        created_at: Set(at.into()),
        ..Default::default()
    }
    .insert(db)
    .await
    .unwrap();
    assert!(personal_account.is_active);
    let workspace = account::ActiveModel {
        id: Set(Uuid::now_v7()),
        tenant_id: Set(organization.id),
        name: Set("Workspace".into()),
        kind: Set("workspace".into()),
        personal_user_id: Set(None),
        created_at: Set(at.into()),
        ..Default::default()
    }
    .insert(db)
    .await
    .unwrap();

    // A user can join both their personal tenant and an organization, and their
    // account membership remains distinct from organization-level membership.
    for (tenant_id, role) in [(personal.id, "owner"), (organization.id, "member")] {
        tenant_member::ActiveModel {
            tenant_id: Set(tenant_id),
            user_id: Set(first_user),
            role: Set(role.into()),
            created_at: Set(at.into()),
        }
        .insert(db)
        .await
        .unwrap();
    }
    for (account_id, role) in [(personal_account.id, "owner"), (workspace.id, "member")] {
        account_member::ActiveModel {
            account_id: Set(account_id),
            user_id: Set(first_user),
            role: Set(role.into()),
            created_at: Set(at.into()),
        }
        .insert(db)
        .await
        .unwrap();
    }
    let mut duplicate = personal.clone().into_active_model();
    duplicate.id = Set(Uuid::now_v7());
    assert!(matches!(
        duplicate.insert(db).await.unwrap_err().sql_err(),
        Some(SqlErr::UniqueConstraintViolation(_))
    ));
    let mut duplicate = personal_account.clone().into_active_model();
    duplicate.id = Set(Uuid::now_v7());
    assert!(matches!(
        duplicate.insert(db).await.unwrap_err().sql_err(),
        Some(SqlErr::UniqueConstraintViolation(_))
    ));
    let duplicate_member = account_member::ActiveModel {
        account_id: Set(workspace.id),
        user_id: Set(first_user),
        role: Set("admin".into()),
        created_at: Set(at.into()),
    };
    assert!(matches!(
        duplicate_member.insert(db).await.unwrap_err().sql_err(),
        Some(SqlErr::UniqueConstraintViolation(_))
    ));
    for sql in [
        format!(
            "UPDATE public.tenant SET personal_user_id = NULL WHERE id = '{}'",
            personal.id
        ),
        format!(
            "UPDATE public.tenant SET personal_user_id = '{second_user}' WHERE id = '{}'",
            organization.id
        ),
        format!(
            "UPDATE public.account SET kind = 'personal' WHERE id = '{}'",
            workspace.id
        ),
        format!(
            "UPDATE public.account SET name = ' ' WHERE id = '{}'",
            workspace.id
        ),
        format!(
            "UPDATE public.tenant_member SET role = 'root' WHERE tenant_id = '{}'",
            organization.id
        ),
        format!(
            "UPDATE public.account_member SET role = 'root' WHERE account_id = '{}'",
            workspace.id
        ),
    ] {
        assert_check_rejected(db, &sql).await;
    }
    assert_rejected(
        db,
        &format!("DELETE FROM public.tenant WHERE id = '{}'", organization.id),
        "23001", // restrict_violation for the explicit ON DELETE RESTRICT action.
    )
    .await;
    assert_rejected(
        db,
        &format!("DELETE FROM public.\"user\" WHERE id = '{first_user}'"),
        "23001",
    )
    .await;

    sync_schema(db).await.unwrap();
    assert_eq!(
        account::Entity::find_by_id(workspace.id)
            .one(db)
            .await
            .unwrap(),
        Some(workspace.clone())
    );
    assert!(
        account_member::Entity::find_by_id((workspace.id, first_user))
            .one(db)
            .await
            .unwrap()
            .is_some()
    );
    account::Entity::delete_by_id(workspace.id)
        .exec(db)
        .await
        .unwrap();
    assert!(
        account_member::Entity::find_by_id((workspace.id, first_user))
            .one(db)
            .await
            .unwrap()
            .is_none()
    );
    assert!(
        tenant_member::Entity::find_by_id((organization.id, first_user))
            .one(db)
            .await
            .unwrap()
            .is_some(),
        "deleting one workspace does not remove organization membership"
    );
}

async fn assert_check_rejected(db: &DatabaseConnection, sql: &str) {
    assert_rejected(db, sql, "23514").await;
}

async fn assert_rejected(db: &DatabaseConnection, sql: &str, expected_code: &str) {
    use sea_orm::{DbErr, RuntimeErr};

    match db.execute_unprepared(sql).await.unwrap_err() {
        DbErr::Exec(RuntimeErr::SqlxError(error)) => match error.as_ref() {
            sqlx::Error::Database(error) => {
                assert_eq!(error.code().as_deref(), Some(expected_code));
            }
            error => panic!("unexpected error: {error}"),
        },
        error => panic!("unexpected error: {error}"),
    }
}
