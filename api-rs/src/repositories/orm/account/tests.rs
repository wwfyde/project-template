use super::*;
use crate::entities::user;
use crate::models::Locale;
use sea_orm::{ConnectionTrait, Database, DbBackend, IntoActiveModel, PaginatorTrait, Statement};

fn input(name: &str) -> UserWrite {
    UserWrite {
        id: UserId(Uuid::now_v7()),
        email: Some(format!("{name}@example.com")),
        nickname: Some(name.to_owned()),
        username: Some(name.to_owned()),
        hashed_password: None,
        is_active: Some(true),
        locale: Locale::ZhCn,
        is_superuser: Some(false),
        created_at: Utc::now(),
        updated_at: None,
    }
}

fn forbidden<T: std::fmt::Debug>(result: Result<T>) {
    assert!(matches!(
        result.unwrap_err().downcast_ref::<RepositoryError>(),
        Some(RepositoryError::Forbidden)
    ));
}

fn conflict<T: std::fmt::Debug>(result: Result<T>) {
    assert!(matches!(
        result.unwrap_err().downcast_ref::<RepositoryError>(),
        Some(RepositoryError::Conflict)
    ));
}

#[tokio::test]
async fn registration_creates_personal_scope_atomically() {
    let db = crate::test_support::database().await;
    let repo = SeaOrmAccountRepository::new(db.clone());
    db.execute_unprepared("CREATE TRIGGER public.reject_account BEFORE INSERT ON account BEGIN SELECT RAISE(ABORT, 'forced account failure'); END").await.unwrap();
    assert!(repo.register_user(&input("rejected")).await.is_err());
    assert_eq!(user::Entity::find().count(&*db).await.unwrap(), 0);
    assert_eq!(tenant::Entity::find().count(&*db).await.unwrap(), 0);
    assert_eq!(tenant_member::Entity::find().count(&*db).await.unwrap(), 0);
    assert_eq!(account::Entity::find().count(&*db).await.unwrap(), 0);
    assert_eq!(account_member::Entity::find().count(&*db).await.unwrap(), 0);
    db.execute_unprepared("DROP TRIGGER public.reject_account")
        .await
        .unwrap();

    let draft = input("alice");
    let alice = repo.register_user(&draft).await.unwrap();
    assert!(alice.uid.0 > 0);
    let access = repo.resolve_account(alice.id.clone(), None).await.unwrap();
    assert_eq!(access.user_id, alice.id);
    assert_eq!(access.role, MemberRole::Owner);
    let accounts = repo.list_accounts(alice.id.clone()).await.unwrap();
    assert_eq!(accounts.len(), 1);
    assert_eq!(accounts[0].kind, AccountKind::Personal);
    assert_eq!(accounts[0].personal_user_id, Some(alice.id.clone()));
    assert_eq!(accounts[0].tenant_id, access.tenant_id);
    let tenants = repo.list_tenants(alice.id.clone()).await.unwrap();
    assert_eq!(tenants.len(), 1);
    assert_eq!(tenants[0].kind, TenantKind::Personal);
    assert_eq!(tenants[0].personal_user_id, Some(alice.id.clone()));
    conflict(repo.register_user(&draft).await);
    assert_eq!(user::Entity::find().count(&*db).await.unwrap(), 1);
    assert_eq!(tenant::Entity::find().count(&*db).await.unwrap(), 1);
}

#[tokio::test]
async fn account_access_requires_both_memberships_and_personal_accounts_are_private() {
    let db = crate::test_support::database().await;
    let repo = SeaOrmAccountRepository::new(db.clone());
    let alice = repo.register_user(&input("alice")).await.unwrap();
    let bob = repo.register_user(&input("bob")).await.unwrap();
    let outsider = repo.register_user(&input("outsider")).await.unwrap();
    let organization = repo
        .create_tenant(alice.id.clone(), "Organization")
        .await
        .unwrap();
    let a = repo
        .create_workspace(alice.id.clone(), organization.id, "A")
        .await
        .unwrap();
    let b = repo
        .create_workspace(alice.id.clone(), organization.id, "B")
        .await
        .unwrap();
    repo.put_tenant_member(
        alice.id.clone(),
        organization.id,
        bob.id.clone(),
        MemberRole::Member,
    )
    .await
    .unwrap();
    repo.put_account_member(alice.id.clone(), a.id, bob.id.clone(), MemberRole::Member)
        .await
        .unwrap();
    assert_eq!(
        repo.resolve_account(bob.id.clone(), Some(a.id))
            .await
            .unwrap()
            .tenant_id,
        organization.id
    );
    forbidden(repo.resolve_account(bob.id.clone(), Some(b.id)).await);
    let bob_accounts = repo.list_accounts(bob.id.clone()).await.unwrap();
    assert_eq!(bob_accounts.len(), 2);
    assert!(bob_accounts.iter().any(|account| account.id == a.id));
    assert!(!bob_accounts.iter().any(|account| account.id == b.id));

    forbidden(
        repo.put_account_member(
            alice.id.clone(),
            a.id,
            outsider.id.clone(),
            MemberRole::Member,
        )
        .await,
    );
    // Even a malformed persisted account membership cannot bypass tenant checks.
    account_member::ActiveModel {
        account_id: Set(a.id.0),
        user_id: Set(outsider.id.0),
        role: Set("member".into()),
        created_at: Set(Utc::now().into()),
    }
    .insert(&*db)
    .await
    .unwrap();
    forbidden(repo.resolve_account(outsider.id.clone(), Some(a.id)).await);

    let personal = repo.resolve_account(alice.id.clone(), None).await.unwrap();
    forbidden(
        repo.resolve_account(bob.id.clone(), Some(personal.account_id))
            .await,
    );
    forbidden(
        repo.put_account_member(
            alice.id.clone(),
            personal.account_id,
            bob.id.clone(),
            MemberRole::Member,
        )
        .await,
    );
    forbidden(
        repo.put_tenant_member(
            alice.id.clone(),
            personal.tenant_id,
            bob.id.clone(),
            MemberRole::Member,
        )
        .await,
    );
    forbidden(
        repo.create_workspace(alice.id.clone(), personal.tenant_id, "Not allowed")
            .await,
    );

    repo.remove_account_member(alice.id.clone(), a.id, bob.id.clone())
        .await
        .unwrap();
    forbidden(repo.resolve_account(bob.id.clone(), Some(a.id)).await);
    assert_eq!(repo.list_accounts(bob.id.clone()).await.unwrap().len(), 1);
    assert!(repo.resolve_account(bob.id, None).await.is_ok());
}

#[tokio::test]
async fn management_roles_cannot_escalate_or_remove_last_owners() {
    let db = crate::test_support::database().await;
    let repo = SeaOrmAccountRepository::new(db);
    let alice = repo.register_user(&input("alice")).await.unwrap();
    let bob = repo.register_user(&input("bob")).await.unwrap();
    let tenant = repo
        .create_tenant(alice.id.clone(), "Organization")
        .await
        .unwrap();
    let a = repo
        .create_workspace(alice.id.clone(), tenant.id, "A")
        .await
        .unwrap();
    repo.put_tenant_member(
        alice.id.clone(),
        tenant.id,
        bob.id.clone(),
        MemberRole::Admin,
    )
    .await
    .unwrap();
    let b = repo
        .create_workspace(bob.id.clone(), tenant.id, "B")
        .await
        .unwrap();
    forbidden(repo.resolve_account(bob.id.clone(), Some(a.id)).await);
    forbidden(repo.resolve_account(alice.id.clone(), Some(b.id)).await);
    forbidden(
        repo.put_tenant_member(bob.id.clone(), tenant.id, bob.id.clone(), MemberRole::Owner)
            .await,
    );
    repo.put_account_member(alice.id.clone(), a.id, bob.id.clone(), MemberRole::Admin)
        .await
        .unwrap();
    forbidden(
        repo.put_account_member(bob.id.clone(), a.id, bob.id.clone(), MemberRole::Owner)
            .await,
    );
    forbidden(
        repo.remove_account_member(bob.id.clone(), a.id, alice.id.clone())
            .await,
    );
    conflict(
        repo.remove_account_member(alice.id.clone(), a.id, alice.id.clone())
            .await,
    );
    conflict(
        repo.put_account_member(alice.id.clone(), a.id, alice.id.clone(), MemberRole::Member)
            .await,
    );
    conflict(
        repo.remove_tenant_member(alice.id.clone(), tenant.id, alice.id.clone())
            .await,
    );
    conflict(
        repo.put_tenant_member(
            alice.id.clone(),
            tenant.id,
            alice.id.clone(),
            MemberRole::Member,
        )
        .await,
    );

    repo.put_tenant_member(
        alice.id.clone(),
        tenant.id,
        bob.id.clone(),
        MemberRole::Owner,
    )
    .await
    .unwrap();
    // Tenant removal cannot orphan B even though another tenant owner remains.
    conflict(
        repo.remove_tenant_member(alice.id.clone(), tenant.id, bob.id.clone())
            .await,
    );
    repo.put_account_member(bob.id.clone(), b.id, alice.id.clone(), MemberRole::Owner)
        .await
        .unwrap();
    repo.remove_tenant_member(alice.id.clone(), tenant.id, bob.id.clone())
        .await
        .unwrap();
    forbidden(repo.resolve_account(bob.id.clone(), Some(a.id)).await);
    forbidden(repo.resolve_account(bob.id.clone(), Some(b.id)).await);
    assert!(repo.resolve_account(bob.id, None).await.is_ok());
}

#[tokio::test]
async fn tenant_admin_removal_cannot_cascade_through_protected_workspace_roles() {
    let db = crate::test_support::database().await;
    let repo = SeaOrmAccountRepository::new(db);
    let owner = repo.register_user(&input("owner")).await.unwrap();
    let admin = repo.register_user(&input("admin")).await.unwrap();
    let target = repo.register_user(&input("target")).await.unwrap();
    let tenant = repo
        .create_tenant(owner.id.clone(), "Organization")
        .await
        .unwrap();
    repo.put_tenant_member(
        owner.id.clone(),
        tenant.id,
        admin.id.clone(),
        MemberRole::Admin,
    )
    .await
    .unwrap();
    repo.put_tenant_member(
        owner.id.clone(),
        tenant.id,
        target.id.clone(),
        MemberRole::Member,
    )
    .await
    .unwrap();
    let ordinary = repo
        .create_workspace(owner.id.clone(), tenant.id, "Ordinary")
        .await
        .unwrap();
    let protected = repo
        .create_workspace(owner.id.clone(), tenant.id, "Protected")
        .await
        .unwrap();
    repo.put_account_member(
        owner.id.clone(),
        ordinary.id,
        target.id.clone(),
        MemberRole::Member,
    )
    .await
    .unwrap();

    for protected_role in [MemberRole::Admin, MemberRole::Owner] {
        repo.put_account_member(
            owner.id.clone(),
            protected.id,
            target.id.clone(),
            protected_role,
        )
        .await
        .unwrap();
        let tenant_before = repo
            .tenant_members(owner.id.clone(), tenant.id)
            .await
            .unwrap();
        let ordinary_before = repo
            .account_members(owner.id.clone(), ordinary.id)
            .await
            .unwrap();
        let protected_before = repo
            .account_members(owner.id.clone(), protected.id)
            .await
            .unwrap();
        if protected_role == MemberRole::Owner {
            assert_eq!(
                protected_before
                    .iter()
                    .filter(|member| member.role == MemberRole::Owner)
                    .count(),
                2,
                "this must be rejected for role protection, not last-owner protection"
            );
        }
        forbidden(
            repo.remove_tenant_member(admin.id.clone(), tenant.id, target.id.clone())
                .await,
        );
        assert_eq!(
            repo.tenant_members(owner.id.clone(), tenant.id)
                .await
                .unwrap(),
            tenant_before
        );
        assert_eq!(
            repo.account_members(owner.id.clone(), ordinary.id)
                .await
                .unwrap(),
            ordinary_before
        );
        assert_eq!(
            repo.account_members(owner.id.clone(), protected.id)
                .await
                .unwrap(),
            protected_before
        );
    }

    // Once every affected role is Member, the tenant Admin may revoke access.
    repo.put_account_member(
        owner.id.clone(),
        protected.id,
        target.id.clone(),
        MemberRole::Member,
    )
    .await
    .unwrap();
    repo.remove_tenant_member(admin.id, tenant.id, target.id.clone())
        .await
        .unwrap();
    assert!(
        !repo
            .tenant_members(owner.id.clone(), tenant.id)
            .await
            .unwrap()
            .iter()
            .any(|member| member.user_id == target.id)
    );
    for account in [ordinary.id, protected.id] {
        assert!(
            !repo
                .account_members(owner.id.clone(), account)
                .await
                .unwrap()
                .iter()
                .any(|member| member.user_id == target.id)
        );
    }
}

#[tokio::test]
async fn disabled_users_tenants_and_accounts_are_rechecked() {
    let db = crate::test_support::database().await;
    let repo = SeaOrmAccountRepository::new(db.clone());
    let alice = repo.register_user(&input("alice")).await.unwrap();
    let tenant = repo
        .create_tenant(alice.id.clone(), "Organization")
        .await
        .unwrap();
    let workspace = repo
        .create_workspace(alice.id.clone(), tenant.id, "Workspace")
        .await
        .unwrap();
    let mut disabled = account::Entity::find_by_id(workspace.id.0)
        .one(&*db)
        .await
        .unwrap()
        .unwrap()
        .into_active_model();
    disabled.is_active = Set(false);
    disabled.update(&*db).await.unwrap();
    forbidden(
        repo.resolve_account(alice.id.clone(), Some(workspace.id))
            .await,
    );

    let personal = repo.resolve_account(alice.id.clone(), None).await.unwrap();
    let mut disabled = tenant::Entity::find_by_id(personal.tenant_id.0)
        .one(&*db)
        .await
        .unwrap()
        .unwrap()
        .into_active_model();
    disabled.is_active = Set(false);
    disabled.update(&*db).await.unwrap();
    forbidden(repo.resolve_account(alice.id.clone(), None).await);
    let mut disabled = user::Entity::find_by_id(alice.id.0)
        .one(&*db)
        .await
        .unwrap()
        .unwrap()
        .into_active_model();
    disabled.is_active = Set(Some(false));
    disabled.update(&*db).await.unwrap();
    forbidden(repo.list_tenants(alice.id.clone()).await);
    forbidden(repo.create_tenant(alice.id, "Forbidden").await);
}

#[tokio::test]
#[ignore = "requires API_RS_ACCOUNT_TEST_DATABASE_URL pointing to an empty disposable PostgreSQL database"]
async fn postgres_owner_changes_are_serialized() {
    let url = std::env::var("API_RS_ACCOUNT_TEST_DATABASE_URL")
        .expect("set API_RS_ACCOUNT_TEST_DATABASE_URL");
    assert!(
        url::Url::parse(&url)
            .unwrap()
            .path()
            .trim_start_matches('/')
            .starts_with("api_rs_account_test")
    );
    let db = Arc::new(Database::connect(url).await.unwrap());
    let empty = db
        .query_one_raw(Statement::from_string(
            DbBackend::Postgres,
            "SELECT to_regclass('public.user') IS NULL AS empty",
        ))
        .await
        .unwrap()
        .unwrap();
    assert!(
        empty.try_get::<bool>("", "empty").unwrap(),
        "use an empty disposable database"
    );
    crate::core::db::sync_schema(&db).await.unwrap();
    let repo = Arc::new(SeaOrmAccountRepository::new(db.clone()));
    let alice = repo.register_user(&input("alice")).await.unwrap();
    let bob = repo.register_user(&input("bob")).await.unwrap();
    let tenant = repo
        .create_tenant(alice.id.clone(), "Organization")
        .await
        .unwrap();
    let workspace = repo
        .create_workspace(alice.id.clone(), tenant.id, "Workspace")
        .await
        .unwrap();
    repo.put_tenant_member(
        alice.id.clone(),
        tenant.id,
        bob.id.clone(),
        MemberRole::Owner,
    )
    .await
    .unwrap();
    repo.put_account_member(
        alice.id.clone(),
        workspace.id,
        bob.id.clone(),
        MemberRole::Owner,
    )
    .await
    .unwrap();
    let (a, b) = tokio::join!(
        repo.put_account_member(
            alice.id.clone(),
            workspace.id,
            alice.id.clone(),
            MemberRole::Member
        ),
        repo.put_account_member(
            bob.id.clone(),
            workspace.id,
            bob.id.clone(),
            MemberRole::Member
        ),
    );
    assert_ne!(
        a.is_ok(),
        b.is_ok(),
        "only one of two last-owner removals may succeed"
    );
    assert_eq!(
        account_member::Entity::find()
            .filter(account_member::Column::AccountId.eq(workspace.id.0))
            .filter(account_member::Column::Role.eq("owner"))
            .count(&*db)
            .await
            .unwrap(),
        1
    );
    let (a, b) = tokio::join!(
        repo.put_tenant_member(
            alice.id.clone(),
            tenant.id,
            alice.id.clone(),
            MemberRole::Member
        ),
        repo.put_tenant_member(
            bob.id.clone(),
            tenant.id,
            bob.id.clone(),
            MemberRole::Member
        ),
    );
    assert_ne!(a.is_ok(), b.is_ok());
    assert_eq!(
        tenant_member::Entity::find()
            .filter(tenant_member::Column::TenantId.eq(tenant.id.0))
            .filter(tenant_member::Column::Role.eq("owner"))
            .count(&*db)
            .await
            .unwrap(),
        1
    );
    db.close_by_ref().await.unwrap();
}
