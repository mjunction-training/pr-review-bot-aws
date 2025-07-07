# **\=========== CODE REVIEW GUIDELINES ===============**

## **Purpose:**

To ensure code quality, maintainability, security, performance, readability, and adherence to team standards. Reviews should be constructive, actionable, and focus on improving the codebase.

## **General Principles:**

* Code must be readable, understandable, and self-explanatory.  
* Follow the principle of least surprise.  
* Prefer clarity over cleverness.  
* Changes must be necessary and minimal in scope.  
* Provide actionable suggestions and code examples where appropriate.  
1. Code Style & Formatting:  
* Follow project-specific style guide (e.g., PEP8 for Python, Google Java Style Guide, ESLint for JavaScript).  
* Ensure proper indentation, spacing, and consistent line endings.  
* Limit line length (usually 80 or 120 characters) for readability.  
* Remove commented-out code unless necessary for historical context (and explain why).  
* Use meaningful and consistent naming conventions (camelCase, snake\_case, PascalCase, kebab-case) for variables, functions, classes, and files.  
* Adhere to established file naming conventions (e.g., kebab-case for CSS/HTML, snake\_case for Python).  
2. Documentation & Comments:  
* Public functions, classes, and complex modules should have comprehensive docstrings/comments explaining their purpose, arguments, return values, and any side effects.  
* Inline comments should explain "why" a particular piece of code exists, not "what" it does (which the code itself should show).  
* Avoid redundant comments that merely re-state the obvious code.  
* Update outdated comments, docstrings, and READMEs to reflect current functionality.  
* Ensure API documentation is clear and consistent for external interfaces.  
3. Code Structure & Modularity:  
* Maintain single responsibility principle (SRP): each function, class, or module should have one clear purpose.  
* Avoid deeply nested conditionals (if/else, loops); refactor for readability and early exits.  
* Keep functions short and focused; ideally, a function should fit on a single screen.  
* Ensure logical grouping of related functions, classes, and files.  
* Promote loose coupling and high cohesion between components.  
* Use appropriate design patterns where they solve a recurring problem elegantly.  
* Break down large files into smaller, more manageable modules.  
4. Error Handling & Robustness:  
* Implement comprehensive error handling (try/catch, graceful degradation) for all potential failure points (e.g., external API calls, file I/O, user input).  
* Provide meaningful error messages that aid debugging and user understanding.  
* Distinguish between expected (e.g., validation errors) and unexpected errors (e.g., system failures).  
* Log errors appropriately with sufficient context (stack traces, relevant variables).  
* Avoid "swallowing" exceptions without logging or re-raising.  
* Consider retry mechanisms for transient failures.  
5. Performance Optimization:  
* Identify and optimize performance bottlenecks (e.g., N+1 queries, inefficient loops, excessive I/O).  
* Avoid unnecessary computations or redundant data processing.  
* Use efficient data structures and algorithms.  
* Be mindful of resource consumption (CPU, memory, network).  
* Implement caching strategies where appropriate.  
* Profile code to identify actual performance issues, don't just guess.  
6. Security Best Practices:  
* **Input Validation**: Validate all user inputs and external data to prevent injection attacks (SQL, XSS, command injection).  
* **Authentication & Authorization**: Ensure proper authentication and granular authorization mechanisms are in place. Avoid hardcoded credentials.  
* **Sensitive Data Handling**: Protect sensitive data (passwords, API keys, PII) at rest and in transit (encryption, secure storage like AWS Secrets Manager/Vault). Avoid logging sensitive data.  
* **Dependency Management**: Regularly update and scan third-party dependencies for known vulnerabilities.  
* **Error Messages**: Avoid verbose error messages that leak sensitive system information.  
* **Access Control**: Implement least privilege principle for all components and users.  
* **Session Management**: Secure session management (e.g., secure cookies, token validation).  
* **Rate Limiting**: Implement rate limiting to prevent abuse and denial-of-service attacks.  
* **Logging & Monitoring**: Ensure sufficient security logging and monitoring for suspicious activities.  
* **Common Vulnerabilities**: Be aware of and guard against OWASP Top 10 vulnerabilities.  
7. Testing & Testability:  
* Include or update unit tests for all new/modified functionality.  
* Use descriptive test names that clearly indicate what is being tested.  
* Tests should be deterministic, isolated, and repeatable.  
* Cover edge cases, boundary values, and error conditions.  
* Ensure adequate test coverage (aim for high coverage, but prioritize meaningful tests over percentage).  
* Write integration tests for critical workflows.  
* Design code to be easily testable (e.g., dependency injection, pure functions).  
8. Readability & Maintainability:  
* Write self-documenting code: use clear variable names, small functions, and logical flow.  
* Avoid excessive complexity; prefer simple solutions.  
* Refactor complex code into smaller, understandable units.  
* Ensure consistency in patterns, abstractions, and idioms across the codebase.  
* Avoid magic numbers/strings; use named constants or enums.  
* Minimize global state and side effects.  
* Consider future extensibility and ease of modification.  
9. Concurrency & Parallelism (If applicable):  
* Identify potential race conditions, deadlocks, and starvation issues.  
* Use appropriate synchronization primitives (locks, semaphores, mutexes) correctly.  
* Be mindful of thread safety and shared mutable state.  
* Understand the implications of concurrent data access.  
* Avoid over-optimization with concurrency if simpler, sequential solutions suffice.  
10. API Design (If applicable):  
* Design consistent, intuitive, and well-documented APIs (REST, GraphQL, gRPC).  
* Use clear and predictable resource naming.  
* Implement proper versioning for APIs.  
* Provide clear error responses with appropriate HTTP status codes.  
* Consider idempotency for write operations.  
* Document request/response schemas and examples.  
11. Infrastructure as Code (IaC):  
* Avoid hardcoding secrets; use secure parameters or environment variables (e.g., AWS Secrets Manager, Vault).  
* Validate and lint templates/scripts (e.g., Terraform, CloudFormation, Ansible).  
* Ensure idempotency of scripts: running them multiple times yields the same result.  
* Keep infrastructure code DRY (Don't Repeat Yourself) and modular.  
* Document infrastructure architecture and deployment procedures.  
12. CI/CD & Automation:  
* Ensure all tests pass before merging.  
* Validate code coverage thresholds.  
* Include relevant linter/static analysis tools in CI pipeline.  
* Automate deployment steps as much as possible.  
* Ensure fast feedback loops in CI/CD pipelines.  
13. UX & Accessibility (Frontend-specific):  
* Validate layout and responsiveness across various devices and screen sizes.  
* Ensure keyboard navigability and proper focus management.  
* Use semantic HTML where applicable to improve accessibility.  
* Provide alt text for images and aria-labels for dynamic elements.  
* Ensure sufficient color contrast and font sizes.  
* Implement clear and consistent user feedback for interactions.  
14. AI/ML Code (If applicable):  
* Ensure model versioning and reproducibility of results.  
* Validate data preprocessing steps and feature engineering.  
* Avoid data leakage in training code (e.g., using test data during training).  
* Document model evaluation metrics, assumptions, and limitations.  
* Implement MLOps practices for model deployment, monitoring, and retraining.  
* Ensure fairness and bias considerations in data and models.

## **Final Checklist Before Approving:**

* \[ \] Code compiles/builds successfully.  
* \[ \] All tests pass and test coverage is acceptable.  
* \[ \] Code follows style and readability standards.  
* \[ \] No unnecessary changes or commented code left.  
* \[ \] Changes are minimal, scoped, and well-justified.  
* \[ \] Code is reviewed with a security-first mindset.  
* \[ \] Documentation (code \+ PR) is sufficient and clear.

Reviewed by: CodeGuardian Bot  
Date: \[Auto-filled\]