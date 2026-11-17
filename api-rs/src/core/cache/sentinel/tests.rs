use super::*;

#[test]
fn server_error_values_trigger_rediscovery_only_for_topology_failures() {
    for (response, expected) in [
        (
            b"-READONLY You can't write against a read only replica.\r\n".as_slice(),
            true,
        ),
        (
            b"-MASTERDOWN Link with MASTER is down.\r\n".as_slice(),
            true,
        ),
        (
            b"-WRONGTYPE Operation against a key holding the wrong kind of value\r\n".as_slice(),
            false,
        ),
    ] {
        let value = redis::parse_redis_value(response).unwrap();
        assert!(matches!(value, Value::ServerError(_)));
        assert_eq!(value_requires_rediscovery(&value), expected);
        assert_eq!(
            error_requires_rediscovery(&value.extract_error().unwrap_err()),
            expected
        );
    }
}

#[test]
fn pipeline_and_transaction_values_preserve_nested_topology_errors() {
    for (response, expected) in [
        (
            b"*2\r\n+OK\r\n-READONLY Replica is read only\r\n".as_slice(),
            true,
        ),
        (
            b"*2\r\n+OK\r\n*2\r\n:1\r\n-MASTERDOWN Primary unavailable\r\n".as_slice(),
            true,
        ),
        (
            b"*2\r\n+OK\r\n*2\r\n:1\r\n-WRONGTYPE Wrong kind of value\r\n".as_slice(),
            false,
        ),
    ] {
        let value = redis::parse_redis_value(response).unwrap();
        let Value::Array(values) = &value else {
            panic!("expected pipeline response");
        };
        assert_eq!(values.iter().any(value_requires_rediscovery), expected);
        assert_eq!(value_requires_rediscovery(&value), expected);
    }
}

#[test]
fn resp3_attributes_do_not_hide_topology_errors() {
    for response in [
        b"|1\r\n+source\r\n+replica\r\n-READONLY Replica is read only\r\n".as_slice(),
        b"|1\r\n+metadata\r\n-MASTERDOWN Primary unavailable\r\n+OK\r\n".as_slice(),
    ] {
        let value = redis::parse_redis_value(response).unwrap();
        assert!(matches!(value, Value::Attribute { .. }));
        assert!(value_requires_rediscovery(&value));
    }
}

#[test]
fn io_errors_trigger_rediscovery() {
    let error = std::io::Error::new(std::io::ErrorKind::ConnectionReset, "connection reset").into();
    assert!(error_requires_rediscovery(&error));
}
