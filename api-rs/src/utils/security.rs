use bcrypt::{DEFAULT_COST, hash, verify};

pub fn get_password_hash(password: &str) -> Result<String, bcrypt::BcryptError> {
    hash(password, DEFAULT_COST)
}

pub fn verify_password(plain_password: &str, hashed_password: &str) -> bool {
    verify(plain_password, hashed_password).unwrap_or(false)
}
