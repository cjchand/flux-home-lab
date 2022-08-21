# SealedSecrets - How to store secrets safely, anywhere

Ultimately, a SealedSecret looks and acts similar - from a config standpoint - to a normal secret. The difference is Flux will decrypt the value and generate a normal Kubernetes secret, which we can reference in our deployment configuration like any other secret.

For example, I manage the secrets needed for the [Teslamate application](#applications) in [`teslamate-postgres-sealed.yaml`](./clusters/dev/apps/teslamate/teslamate-postgres-sealed.yaml)

```apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  creationTimestamp: null
  name: teslamate-postgres
  namespace: teslamate
spec:
  encryptedData:
    encryption_key: AgC38nn9jPRTBUDLqc/4dut2OU4VTjt0zDs9EUjC5ncA+pi5lqUkEQZOqvJzsE6ujFcuERCRiuk+nOc+KDEBQzv9etHUY9a9cum/qALkqrXL6/bAha0q1YSus6fH4LfOzybaGt3EA2pYvXWNn4wG1EdgTtpq1DC4Cwftelwg2MlTGpWr821X5MfaqhOo7NKr3fE2/hHHD+wmZSAMj9JtyLeIIVQItyZP6ll2JVJPWeF48kW0gu3YwKLhjsfdP/k7Lx6CaVZybBXgvOZTJt47iYwAwT1GH6Fxs0ZhxVaLpc4zgs5hE1Fw0qcWRcP7QRNQ8ObIJmEOsa1hoF3yZU4Zvw9s5x1q9LY0jJg+J7JgrizWp041pM1c3Xjwwk+HqVLR0z6Jd3Su3HTq5H+YMJvltK5eKYubknGlCwM8HMt1I9Pxl4chKZTLusFkeMUD0y8Svce40P84M0IXV+ht+B7NyBGrDLgPrmdt7VoPvL/da+R6HN3zclAVcUQ0cI8NnilwWVhqdA4TxsWHUCMHBGLdkwWBixV89hnOOiGLagluamZeo961fkr30uErAr0nqZGv2LwwoKSSoj2DKWOG7vvE3XSO+I4dg+OvrUFfdLl05SOU822o/aGFbZ1oQVAyaqGEcRq8nGRudvHS+bdxn2VwtBie81dSmNRL8FG8R9MFqNGuP50Ikgj1kqV7wb34XcZOQLCaomPGcVF4Dfdq1RtuZDl7UWQN0PiHT2tlzwwY6EYOnoVnD+fm5ctIjGebx/XRhTq5//E=
    postgres_user_pass: AgB80/FepJlSMmyCDpjfcQH+g4cj57+o2YmVClATiNzgjDypJmBGd9sGp2OYrzt3vRNo8pXoqwRl+8Qf+26m05goPiC+rD17MJQQKcmO5y4Uki7TNC/aQprpHxAEe1PkKBiU3sDE2gLMNfDUbohP71WS2WCY0lm5bqfujaEnPuLmb22dRt2Z9nUb2mHCx+610sHHw5Rd7+Qfjn0ssQLMUckS3ElVnuOReoPhqGMNRTkrIc+pR1Oa0BX/DhWVU4yfIFD45F/sEDbpYdHb4cZ4XYpQJK0N9gEk5g+s5LWAhTaqXv5EeF0BZa+cfsIHVvQv6OdK8r7Yd3N/Y/si85OiZLH9HsgadHsHp3tZB0GoOZF+tjDxJ+NxexQ1nbmfHCO5ozcVWTl1QfIRW+EYsgA4FdAbBzSHDrGm/dVWHmlagquqUyrOUTl9LgkBJjHPmvsjmJ+Cgpgpab4rFCA29Y3TAcC2q5htl0EOM61iWwULDpfw15WLCnOT7WecyjHaYrK5QaY4jWLt7Vd1DquXG39KfA/AgYsqWwAk5SdHi76TEwUfA4Gpa1FrjoMjeGMznnJ19d26l2/SRD3a0YyqqNUhe6kd+O8iowJ/h6/WuYAMcoyzWjOErc1M0aWK1AY1h9BBrYvYjfVB5hXy5atKwDMDjRcvkwDGwb9HnH1y80RPJXlLcYmIwx1BuutjCVbKW9Ua7ICTGUzo1TxSToAYNH+uXA==
    teslamate_user_pass: AgBHBJtR/fegjJ24XHAjjbxT1COI7i1LXCZKAj6S3PNPKdOsPuIFG1R4KKAXHgoZVG//yRhXY1IBgMAn1eM5RdsGTqXfxoneqeKat9YssQfLMIaamSgG9ax+TEziBX6QE52Aq50nrT2/KwpX8r4z41WKK3H7yJtCOMhB60sIUjmcdcv4/jPojYBtMfsHQNknorqON1i0eiknSzQMqRbITh2WJ/VjfR3fktph6cTj//B3626a6fp4GlxPOahijq+Gqrk2D0eq/+IxlhYY9jZb8kraEa7WQVu9jYSEup7O0IvDOa4/EQCeuJIIFJ6TKZMUgKCVTg31yWYocPLOvbjNEf7GaEYDI6Jdkit+3neJUr0nRSHjAXUgohbzpVUXcvsjYLExB2ZplIBhye3ybYG2rJLWz8qgcSeG8CRZfnCBEJAspHuDHFh+esOtcDmZhp5zMU5WObpGOtl3upjiKut6G6sKokxy2sqyTaRRKEWxd055Xc12zsfefygF3IbsPmU0YvGvKP/B/nn55/u18gN4aj8AFuUogIUfbYJY1xPpp7Oi/Tgj7nKo0xkCCzU3I5aqz4knSDFa+tyMOIExaNBhNK3phHMm+CylUpUdtvIQc7hk18xuoh4tfPkBZ0jo6aiof6rapzM5AQpEtw7wRXOmsIghIGYVvoDfxAKv8J5msgh5NtePko5KfEQl6YYOSWPcZzm3BpFapg5q2/e9xIIbHQ==
  template:
    metadata:
      creationTimestamp: null
      name: teslamate-postgres
      namespace: teslamate

```
Those values under `spec.encryptedData` were encrypted using the [process detailed in the Flux documenation](https://fluxcd.io/docs/guides/sealed-secrets/#encrypt-secrets), but the short version is:

* Once SealedSecrets are installed in the cluster, you can fetch its public key
* Using that key, you take a vanilla Kubernetes secrets file and pass it through `kubeseal`, which generates a file like the one above
* Delete the vanilla secret (which you didn't commit to code, right? ;) ) and commit the encrypted file

These can then be referenced in your deployment manifests, such as this example from the Postgres HelmRelease:

``` 
    global:
      imagePullSecrets: []
      imageRegistry: ""
      postgresql:
        auth:
          database: teslamate
          existingSecret: "teslamate-postgres"
          secretKeys:
            adminPasswordKey: "postgres_user_pass"
            replicationPasswordKey: ""
            userPasswordKey: "teslamate_user_pass"
          username: teslamate
```
Here, we point to an existing secret in the cluster: `teslamate-postgres`, which we specified in `template.metadata.name` of our SealedSecret above. That allows us to specify the keys within that secret in our config, as seen with `adminPasswordKey` and `userPasswordKey` above.