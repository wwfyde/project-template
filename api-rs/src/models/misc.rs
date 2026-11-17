use std::any::Any;
use std::collections::HashMap;

struct Frontmatter {
    title: String,
    description: String,
    categories: Vec<String>,
    /// Alternative names or titles for the document (especially useful in Obsidian for linking).
    aliases: String,
    tags: Vec<String>,
    icon: String,
    cover: String,
    metadata: HashMap<String, Box<dyn Any>>,
}
